"""Chat between donor, patient and hospital: access, privacy, closing and reports."""
from datetime import datetime, timedelta

import pytest

from conftest import PASSWORD, login, make_donor, make_hospital, make_patient, make_request
from models import (STATUS_CANCELLED, Admin, ChatMessage, ChatReport, DonationResponse,
                    Notification, AccountNotification, db)
from utils import allocation, chat, privacy, ratelimit
from utils.maintenance import retention_cleanup


@pytest.fixture
def offer(scene):
    """The first donor has offered to help with the 3-unit request."""
    return allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)


def _client(app, user, role):
    c = app.test_client()
    login(c, user, role)
    return c


def _admin():
    a = Admin(name="Admin Person", email="admin-chat@example.com")
    a.set_password(PASSWORD)
    db.session.add(a)
    db.session.commit()
    return a


def _typed():
    """How many messages people typed (automatic timeline lines do not count)."""
    return ChatMessage.query.filter(ChatMessage.kind != "event").count()


def _send(c, offer, text):
    return c.post(f"/messages/{offer.id}/send", json={"body": text})


# ----------------------------------------------------------------------
# Access control
# ----------------------------------------------------------------------
def test_only_the_three_participants_can_open_a_thread(app, scene, offer):
    for user, role in ((scene.donors[0], "donor"), (scene.patient, "patient"),
                       (scene.hospital, "hospital")):
        assert _client(app, user, role).get(f"/messages/{offer.id}").status_code == 200


def test_outsiders_get_404_not_a_hint(app, scene, offer):
    outsiders = [(scene.donors[1], "donor"), (make_patient(), "patient"), (make_hospital(), "hospital")]
    for user, role in outsiders:
        c = _client(app, user, role)
        assert c.get(f"/messages/{offer.id}").status_code == 404
        assert c.get(f"/messages/{offer.id}/poll").status_code == 404
        assert _send(c, offer, "hi").status_code == 404
    assert _typed() == 0


def test_anonymous_is_sent_to_login(client, offer):
    assert client.get(f"/messages/{offer.id}").status_code == 302
    assert client.post(f"/messages/{offer.id}/send", json={"body": "x"}).status_code == 302


def test_unknown_thread_is_404(app, scene):
    assert _client(app, scene.patient, "patient").get("/messages/99999").status_code == 404


def test_admin_cannot_read_until_a_report_exists(app, scene, offer):
    admin = _admin()
    c = _client(app, admin, "admin")
    assert c.get(f"/messages/{offer.id}").status_code == 404
    chat.report("patient", scene.patient, offer, "asked me for money")
    assert c.get(f"/messages/{offer.id}").status_code == 200
    assert _send(c, offer, "admin writing").status_code == 403      # admins never write


# ----------------------------------------------------------------------
# Sending, reading, privacy of what is shown
# ----------------------------------------------------------------------
def test_conversation_round_trip_and_unread_badges(app, scene, offer):
    donor_c = _client(app, scene.donors[0], "donor")
    patient_c = _client(app, scene.patient, "patient")
    r = _send(donor_c, offer, "I can come at 5pm")
    assert r.status_code == 201 and r.get_json()["message"]["mine"] is True
    assert chat.unread_total("patient", scene.patient.id) == 1
    assert chat.unread_total("hospital", scene.hospital.id) == 1
    assert chat.unread_total("donor", scene.donors[0].id) == 0       # own message is not "new"

    data = patient_c.get(f"/messages/{offer.id}/poll?after=0").get_json()
    assert [m["body"] for m in data["messages"] if m["kind"] == "text"] == ["I can come at 5pm"]
    assert data["messages"][0]["mine"] is False and data["can_post"] is True
    assert chat.unread_total("patient", scene.patient.id) == 0       # polling marks it read

    _send(patient_c, offer, "Thank you, please bring ID")
    after = donor_c.get(f"/messages/{offer.id}/poll?after={data['messages'][-1]['id']}").get_json()
    assert [m["body"] for m in after["messages"] if m["kind"] == "text"] == ["Thank you, please bring ID"]


def test_form_post_works_without_javascript(app, scene, offer):
    c = _client(app, scene.patient, "patient")
    r = c.post(f"/messages/{offer.id}/send", data={"body": "Hello donor"})
    assert r.status_code == 302
    assert "Hello donor" in c.get(f"/messages/{offer.id}").get_data(as_text=True)


def test_messages_are_html_escaped(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    _send(c, offer, "<script>alert(1)</script><b>bold</b>")
    page = c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_donor_sees_initials_not_the_patient_name(app, scene, offer):
    _send(_client(app, scene.patient, "patient"), offer, "Hello")
    page = _client(app, scene.donors[0], "donor").get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "Test Patient Name" not in page and "Secret ward note" not in page
    assert "Patient (T. P.)" in page


@pytest.mark.parametrize("text", ["", "   \n  ", "x" * 1001])
def test_invalid_messages_are_refused(app, scene, offer, text):
    r = _send(_client(app, scene.donors[0], "donor"), offer, text)
    assert r.status_code == 400 and r.get_json()["error"]
    assert _typed() == 0


def test_control_characters_are_stripped(app, scene, offer):
    r = _send(_client(app, scene.donors[0], "donor"), offer, "hi\x00 there\x07")
    assert r.get_json()["message"]["body"] == "hi there"


def test_rate_limit(app, scene, offer):
    ratelimit.clear_all()
    c = _client(app, scene.donors[0], "donor")
    codes = [_send(c, offer, f"m{i}").status_code for i in range(app.config["CHAT_RATE_LIMIT"] + 3)]
    assert codes[:app.config["CHAT_RATE_LIMIT"]] == [201] * app.config["CHAT_RATE_LIMIT"]
    assert set(codes[app.config["CHAT_RATE_LIMIT"]:]) == {400}


def test_only_first_unread_message_notifies_and_no_text_is_leaked(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    before = AccountNotification.query.count()
    for i in range(4):
        _send(c, offer, f"secret-medical-text {i}")
    new = AccountNotification.query.filter(AccountNotification.message.like("New message%")).all()
    assert len(new) == 2                                    # patient + hospital, once each
    assert all("secret" not in n.message for n in new)
    assert AccountNotification.query.count() == before + 2


def test_donor_is_notified_when_the_patient_writes(app, scene, offer):
    _send(_client(app, scene.patient, "patient"), offer, "Hello")
    assert Notification.query.filter(Notification.donor_id == scene.donors[0].id,
                                     Notification.message.like("New message%")).count() == 1


# ----------------------------------------------------------------------
# Closing
# ----------------------------------------------------------------------
def test_thread_becomes_read_only_when_offer_is_cancelled(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    _send(c, offer, "before")
    allocation.cancel_response(offer.id, "donor", scene.donors[0].id)
    r = _send(c, offer, "after")
    assert r.status_code == 400 and "read-only" in r.get_json()["error"]
    page = c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "before" in page and 'id="chatForm"' not in page      # history stays readable


def test_thread_closes_when_request_is_cancelled(app, scene, offer):
    allocation.close_request(scene.request.id, "patient", scene.patient.id, "no longer needed")
    r = _send(_client(app, scene.patient, "patient"), offer, "hello?")
    assert r.status_code == 400


def test_thread_closes_after_hospital_confirms_the_donation(app, scene, offer):
    allocation.confirm_donation(scene.hospital, offer.id)
    r = _send(_client(app, scene.donors[0], "donor"), offer, "thanks!")
    assert r.status_code == 400


def test_chat_never_changes_request_or_units(app, scene, offer):
    _send(_client(app, scene.donors[0], "donor"), offer, "I donated, mark it done")
    db.session.expire_all()
    assert scene.request.units_confirmed == 0 and scene.request.status == "Approved"
    assert not allocation.check_consistency()          # totals still agree with donation records


# ----------------------------------------------------------------------
# Reports
# ----------------------------------------------------------------------
def test_report_lock_blocks_posting_and_dismiss_does_not(app, scene, offer):
    admin = _admin()
    donor_c = _client(app, scene.donors[0], "donor")
    r = donor_c.post(f"/messages/{offer.id}/report", data={"reason": "Asked for payment"})
    assert r.status_code == 302 and ChatReport.query.count() == 1
    admin_c = _client(app, admin, "admin")
    assert "Asked for payment" in admin_c.get("/admin/chat-reports").get_data(as_text=True)
    rep = ChatReport.query.first()
    admin_c.post(f"/admin/chat-reports/{rep.id}/resolve", data={"action": "lock", "note": "scam"})
    assert ChatReport.query.first().status == "Thread locked"
    assert _send(donor_c, offer, "hi").status_code == 400
    assert "locked" in _send(donor_c, offer, "hi").get_json()["error"]


def test_dismissed_report_keeps_thread_open(app, scene, offer):
    admin = _admin()
    chat.report("patient", scene.patient, offer, "just checking")
    chat.resolve_report(ChatReport.query.first().id, admin, "dismiss")
    assert _send(_client(app, scene.donors[0], "donor"), offer, "still ok").status_code == 201


def test_report_needs_a_reason_and_participants_only(app, scene, offer):
    with pytest.raises(chat.ChatError):
        chat.report("donor", scene.donors[0], offer, "x")
    with pytest.raises(chat.ChatError):
        chat.report("donor", scene.donors[1], offer, "I am not in this thread")


def test_only_admin_can_use_the_report_queue(app, scene, offer):
    assert _client(app, scene.donors[0], "donor").get("/admin/chat-reports").status_code == 403
    assert _client(app, scene.hospital, "hospital").post("/admin/chat-reports/1/resolve",
                                                           data={"action": "lock"}).status_code == 403


# ----------------------------------------------------------------------
# Privacy: erasure, export, retention
# ----------------------------------------------------------------------
def test_export_contains_own_messages_only(app, scene, offer):
    _send(_client(app, scene.donors[0], "donor"), offer, "mine")
    _send(_client(app, scene.patient, "patient"), offer, "theirs")
    data = privacy.export_data("donor", scene.donors[0])
    assert [m["message"] for m in data["chat_messages_sent"]] == ["mine"]


def test_erasing_a_donor_removes_what_they_wrote(app, scene, offer):
    _send(_client(app, scene.donors[0], "donor"), offer, "my phone is 0300")
    donor_id = scene.donors[0].id
    privacy.erase_donor(scene.donors[0])
    assert ChatMessage.query.filter_by(sender_role="donor", sender_id=donor_id).count() == 0
    assert db.session.get(DonationResponse, offer.id) is None       # unverified offer and thread are gone
    assert ChatMessage.query.count() == 0


def test_erasing_a_patient_removes_their_messages(app, scene, offer):
    _send(_client(app, scene.patient, "patient"), offer, "private words")
    privacy.erase_patient(scene.patient)
    assert ChatMessage.query.filter_by(sender_role="patient").count() == 0


def test_retention_deletes_chat_after_the_request_closed_long_ago(app, scene, offer):
    _send(_client(app, scene.donors[0], "donor"), offer, "old")
    allocation.close_request(scene.request.id, "patient", scene.patient.id, "done")
    db.session.expire_all()
    scene.request.closed_at = datetime.utcnow() - timedelta(days=app.config["CHAT_RETENTION_DAYS"] + 1)
    db.session.commit()
    result = retention_cleanup(app.config)
    assert result["chat_messages"] >= 1 and ChatMessage.query.count() == 0


def test_retention_keeps_recent_chat(app, scene, offer):
    _send(_client(app, scene.donors[0], "donor"), offer, "fresh")
    allocation.close_request(scene.request.id, "patient", scene.patient.id, "done")
    assert retention_cleanup(app.config)["chat_messages"] == 0


# ----------------------------------------------------------------------
# CSRF still protects the JSON endpoint
# ----------------------------------------------------------------------
def test_json_post_without_csrf_header_is_rejected(tmp_path, scene_factory=None):
    import app as app_module
    from config import TestingConfig

    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'csrf.db'}"
        WTF_CSRF_ENABLED = True

    flask_app = app_module.create_app(Cfg)
    with flask_app.app_context():
        patient = make_patient()
        hospital = make_hospital()
        donor = make_donor("O+")
        req = make_request(patient, hospital)
        resp = allocation.pledge(donor, req.id, consent_to_share=True)
        c = flask_app.test_client()
        with c.session_transaction() as s:
            s["user_id"], s["role"], s["_csrf"] = donor.id, "donor", "tok"
        assert c.post(f"/messages/{resp.id}/send", json={"body": "hi"}).status_code == 400
        ok = c.post(f"/messages/{resp.id}/send", json={"body": "hi"}, headers={"X-CSRFToken": "tok"})
        assert ok.status_code == 201
        db.session.remove()
        db.engine.dispose()

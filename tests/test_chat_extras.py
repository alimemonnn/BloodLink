"""Chat extras: timeline events, donation plan, calendar file, quick replies and shared location."""
import sqlite3
from datetime import datetime, timedelta

import pytest

from conftest import PASSWORD, login, make_hospital, make_patient
from models import AuditLog, ChatMessage, db
from utils import allocation, chat, privacy
from utils.maintenance import expire_old_requests, retention_cleanup


@pytest.fixture
def offer(scene):
    return allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)


def _client(app, user, role):
    c = app.test_client()
    login(c, user, role)
    return c


def _events(offer):
    db.session.expire_all()
    return [m.body for m in ChatMessage.query.filter_by(response_id=offer.id, kind="event").order_by(ChatMessage.id)]


def _where(c, offer, lat=27.7052, lng=68.8574, acc=18):
    return c.post(f"/messages/{offer.id}/location", json={"lat": lat, "lng": lng, "accuracy": acc})


# ----------------------------------------------------------------------
# Timeline events
# ----------------------------------------------------------------------
def test_offer_and_hospital_actions_write_timeline_lines(app, scene, offer):
    assert "offered 1 unit" in _events(offer)[0]
    allocation.mark_contacted(scene.hospital, offer.id)
    when = datetime.utcnow() + timedelta(days=1)
    allocation.schedule_appointment(scene.hospital, offer.id, when)
    allocation.confirm_donation(scene.hospital, offer.id)
    ev = _events(offer)
    assert any("marked this donor as contacted" in e for e in ev)
    assert any("Appointment scheduled for" in e for e in ev)
    assert any("Donation confirmed by the hospital: 1 unit(s)" in e for e in ev)


def test_cancel_ineligible_and_closed_request_are_recorded(app, scene):
    a = allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)
    b = allocation.pledge(scene.donors[1], scene.request.id, consent_to_share=True)
    allocation.cancel_response(a.id, "donor", scene.donors[0].id)
    allocation.mark_ineligible(scene.hospital, b.id, note="private screening detail")
    assert "The donor cancelled this offer." in _events(a)
    inel = _events(b)
    assert "The hospital could not accept this donation this time." in inel
    assert not any("private screening detail" in e for e in inel)        # notes never reach the chat
    c = allocation.pledge(scene.donors[2], scene.request.id, consent_to_share=True)
    allocation.close_request(scene.request.id, "patient", scene.patient.id, "no longer needed")
    assert any("This request was closed" in e for e in _events(c))


def test_events_do_not_create_unread_badges_or_chat_notifications(app, scene, offer):
    allocation.mark_contacted(scene.hospital, offer.id)
    assert chat.unread_total("patient", scene.patient.id) == 0
    assert chat.unread_total("donor", scene.donors[0].id) == 0
    page = _client(app, scene.patient, "patient").get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "chat-event" in page and "The hospital marked this donor as contacted." in page


def test_events_appear_by_polling(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    last = c.get(f"/messages/{offer.id}/poll?after=0").get_json()["messages"][-1]["id"]
    allocation.mark_contacted(scene.hospital, offer.id)
    data = c.get(f"/messages/{offer.id}/poll?after={last}").get_json()
    assert [m["kind"] for m in data["messages"]] == ["event"]
    assert data["messages"][0]["name"] == "BloodLink"


# ----------------------------------------------------------------------
# Donation plan and calendar file
# ----------------------------------------------------------------------
def test_plan_card_shows_hospital_directions_and_appointment(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    page = c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert scene.hospital.hospital_name in page and "google.com/maps/search" in page
    assert "Not scheduled yet" in page and 'id="planIcs"' in page
    allocation.schedule_appointment(scene.hospital, offer.id, datetime.utcnow() + timedelta(days=2))
    data = c.get(f"/messages/{offer.id}/poll?after=0").get_json()
    assert data["plan"]["appointment"] and data["plan"]["status"] == "Appointment Scheduled"


def test_calendar_file(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    assert c.get(f"/messages/{offer.id}/appointment.ics").status_code == 404      # nothing scheduled yet
    when = datetime.utcnow().replace(microsecond=0) + timedelta(days=1)
    allocation.schedule_appointment(scene.hospital, offer.id, when)
    for user, role in ((scene.donors[0], "donor"), (scene.patient, "patient"), (scene.hospital, "hospital")):
        r = _client(app, user, role).get(f"/messages/{offer.id}/appointment.ics")
        assert r.status_code == 200 and r.mimetype == "text/calendar"
    text = r.get_data(as_text=True)
    assert "BEGIN:VEVENT" in text and f"DTSTART:{when:%Y%m%dT%H%M%S}" in text and "\r\n" in text
    assert "photo ID" in text


def test_calendar_file_is_private(app, scene, offer):
    allocation.schedule_appointment(scene.hospital, offer.id, datetime.utcnow() + timedelta(days=1))
    assert _client(app, scene.donors[1], "donor").get(f"/messages/{offer.id}/appointment.ics").status_code == 404
    assert app.test_client().get(f"/messages/{offer.id}/appointment.ics").status_code == 302


# ----------------------------------------------------------------------
# Quick replies and right-to-left text
# ----------------------------------------------------------------------
def test_quick_replies_are_role_specific_and_work_without_javascript(app, scene, offer):
    donor_c = _client(app, scene.donors[0], "donor")
    page = donor_c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "I&#39;m on my way" in page and "Are you still able to come?" not in page
    r = donor_c.post(f"/messages/{offer.id}/send", data={"body": "I've arrived"})
    assert r.status_code == 302
    assert ChatMessage.query.filter_by(kind="text", body="I've arrived").count() == 1
    hosp = _client(app, scene.hospital, "hospital").get(f"/messages/{offer.id}").get_data(as_text=True)
    assert 'id="quickForm"' not in hosp


def test_urdu_and_sindhi_text_round_trips_and_is_marked_auto_direction(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    for text in ("میں آ رہا ہوں", "مان اچي رهيو آهيان"):
        assert _send_text(c, offer, text).status_code == 201
    page = c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "میں آ رہا ہوں" in page and "مان اچي رهيو آهيان" in page
    assert 'class="chat-body" dir="auto"' in page and 'dir="auto"' in page


def _send_text(c, offer, text):
    return c.post(f"/messages/{offer.id}/send", json={"body": text})


# ----------------------------------------------------------------------
# Shared location
# ----------------------------------------------------------------------
def test_donor_and_patient_can_share_and_everyone_in_the_thread_sees_it(app, scene, offer):
    r = _where(_client(app, scene.donors[0], "donor"), offer, 27.705234567, 68.857411111, 18)
    assert r.status_code == 201
    m = r.get_json()["message"]
    assert m["kind"] == "location" and m["location"]["state"] == "ok" and m["location"]["accuracy"] == 18
    assert "27.70523,68.85741" in m["location"]["google"]                  # rounded to about a metre
    stored = ChatMessage.query.filter_by(kind="location").one()
    assert (stored.lat, stored.lng) == (27.70523, 68.85741)
    for user, role in ((scene.patient, "patient"), (scene.hospital, "hospital")):
        data = _client(app, user, role).get(f"/messages/{offer.id}/poll?after=0").get_json()
        loc = [x for x in data["messages"] if x["kind"] == "location"][0]
        assert loc["location"]["state"] == "ok" and "openstreetmap.org" in loc["location"]["osm"]
    assert _where(_client(app, scene.patient, "patient"), offer).status_code == 201


def test_hospital_cannot_send_a_location_and_strangers_get_404(app, scene, offer):
    assert _where(_client(app, scene.hospital, "hospital"), offer).status_code == 403
    assert chat.LOCATION_ROLES == ("donor", "patient")
    assert _where(_client(app, scene.donors[1], "donor"), offer).status_code == 404
    assert _where(_client(app, make_patient(), "patient"), offer).status_code == 404
    assert _where(app.test_client(), offer).status_code == 302
    assert ChatMessage.query.filter_by(kind="location").count() == 0


@pytest.mark.parametrize("lat,lng", [(91, 10), (-91, 10), (10, 181), (10, -181), ("abc", 10), (None, 10),
                                      ("nan", 10), (10, "inf")])
def test_invalid_coordinates_are_rejected(app, scene, offer, lat, lng):
    r = _client(app, scene.donors[0], "donor").post(f"/messages/{offer.id}/location",
                                                    json={"lat": lat, "lng": lng})
    assert r.status_code == 400 and r.get_json()["error"]
    assert ChatMessage.query.filter_by(kind="location").count() == 0


def test_location_is_rate_limited(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    codes = [_where(c, offer).status_code for _ in range(app.config["CHAT_LOCATION_LIMIT"] + 2)]
    assert codes[:app.config["CHAT_LOCATION_LIMIT"]] == [201] * app.config["CHAT_LOCATION_LIMIT"]
    assert set(codes[app.config["CHAT_LOCATION_LIMIT"]:]) == {400}


def test_no_location_after_the_thread_closes(app, scene, offer):
    allocation.cancel_response(offer.id, "donor", scene.donors[0].id)
    assert _where(_client(app, scene.donors[0], "donor"), offer).status_code == 400


def test_location_stops_being_shown_after_six_hours_and_is_then_erased(app, scene, offer):
    c = _client(app, scene.donors[0], "donor")
    _where(c, offer)
    msg = ChatMessage.query.filter_by(kind="location").one()
    msg.created_at = datetime.utcnow() - timedelta(hours=app.config["CHAT_LOCATION_VISIBLE_HOURS"] + 1)
    db.session.commit()
    patient_c = _client(app, scene.patient, "patient")
    loc = patient_c.get(f"/messages/{offer.id}/poll?after=0").get_json()["messages"][-1]["location"]
    assert loc["state"] == "expired" and "google" not in loc
    page = patient_c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "27.7052" not in page and "no longer shown" in page
    expire_old_requests(force=True)                                       # still inside 24 h: kept
    assert db.session.get(ChatMessage, msg.id).lat is not None
    msg.created_at = datetime.utcnow() - timedelta(hours=app.config["CHAT_LOCATION_RETENTION_HOURS"] + 1)
    db.session.commit()
    expire_old_requests(force=True)
    db.session.expire_all()
    erased = db.session.get(ChatMessage, msg.id)
    assert erased.lat is None and erased.lng is None and erased.accuracy_m is None
    assert erased.body == "Shared a location"                             # the line stays, the position goes


def test_daily_cleanup_also_erases_old_locations(app, scene, offer):
    _where(_client(app, scene.donors[0], "donor"), offer)
    msg = ChatMessage.query.filter_by(kind="location").one()
    msg.created_at = datetime.utcnow() - timedelta(hours=30)
    db.session.commit()
    assert retention_cleanup(app.config)["locations_erased"] == 1


def test_administrators_never_see_coordinates(app, scene, offer):
    from models import Admin
    _where(_client(app, scene.donors[0], "donor"), offer)
    chat.report("patient", scene.patient, offer, "reporting for review")
    a = Admin(name="Admin Person", email="admin-loc@example.com")
    a.set_password(PASSWORD)
    db.session.add(a)
    db.session.commit()
    c = _client(app, a, "admin")
    page = c.get(f"/messages/{offer.id}").get_data(as_text=True)
    poll = c.get(f"/messages/{offer.id}/poll?after=0").get_data(as_text=True)
    assert "hidden for administrators" in page
    assert "27.7052" not in page and "27.7052" not in poll


def test_audit_log_records_that_a_location_was_shared_but_not_where(app, scene, offer):
    _where(_client(app, scene.donors[0], "donor"), offer, 27.70523, 68.85741)
    row = AuditLog.query.filter_by(action="chat.location").one()
    assert "27.7" not in (row.detail or "") and "68.8" not in (row.detail or "")


def test_export_and_erasure_cover_locations(app, scene, offer):
    _where(_client(app, scene.donors[0], "donor"), offer, 27.70523, 68.85741, 20)
    exp = privacy.export_data("donor", scene.donors[0])["chat_messages_sent"]
    assert exp[0]["type"] == "location" and exp[0]["location"]["lat"] == 27.70523
    privacy.erase_donor(scene.donors[0])
    assert ChatMessage.query.filter_by(kind="location").count() == 0


def test_location_never_appears_in_notifications(app, scene, offer):
    from models import AccountNotification
    _where(_client(app, scene.donors[0], "donor"), offer, 27.70523, 68.85741)
    assert not any("27.7" in n.message for n in AccountNotification.query.all())


def test_browser_may_use_geolocation_on_this_site_only(client):
    assert "geolocation=(self)" in client.get("/").headers["Permissions-Policy"]


# ----------------------------------------------------------------------
# Upgrading a database that already has the earlier chat table
# ----------------------------------------------------------------------
def test_existing_chat_table_gets_the_new_columns_without_losing_messages(tmp_path):
    import app as app_module
    from config import TestingConfig
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, response_id INTEGER NOT NULL, "
                "sender_role VARCHAR(20) NOT NULL, sender_id INTEGER NOT NULL, body VARCHAR(1000) NOT NULL, "
                "created_at DATETIME NOT NULL)")
    con.execute("INSERT INTO chat_messages VALUES (1, 1, 'donor', 1, 'old message', '2026-10-15 10:00:00')")
    con.commit(); con.close()

    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"

    flask_app = app_module.create_app(Cfg)
    with flask_app.app_context():
        cols = {c[1] for c in sqlite3.connect(path).execute("PRAGMA table_info(chat_messages)")}
        assert {"kind", "lat", "lng", "accuracy_m"} <= cols
        old = db.session.get(ChatMessage, 1)
        assert old.body == "old message" and old.kind == "text"
        db.session.remove()
        db.engine.dispose()

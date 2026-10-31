"""SMS / WhatsApp / push alerts, appointment reminders, escalation and distance-aware matching."""
from datetime import datetime, timedelta

import pytest

from conftest import PASSWORD, login, make_donor, make_hospital, make_patient, make_request
from models import (AuditLog, BloodRequest, DonationResponse, Notification, OutboxMessage,
                    PushSubscription, db)
from utils import allocation, channels, geo, jobs, notifications, privacy
from utils.matching import rank_donors


def _opt(donor, sms=False, wa=False, email=False):
    donor.sms_opt_in, donor.whatsapp_opt_in, donor.email_opt_in = sms, wa, email
    db.session.commit()
    return donor


def _outbox(**kw):
    return OutboxMessage.query.filter_by(**kw).all()


# --------------------------------------------------------------------- numbers
@pytest.mark.parametrize("raw,expected", [
    ("0300-1234567", "+923001234567"), ("+92 300 1234567", "+923001234567"),
    ("0092 300 1234567", "+923001234567"), ("03001234567", "+923001234567"),
    ("12", None), ("", None), (None, None), ("+1 (415) 555-0100", "+14155550100")])
def test_normalize_phone(raw, expected):
    assert channels.normalize_phone(raw) == expected


# ------------------------------------------------------------- queueing alerts
def test_only_the_channels_a_donor_chose_are_queued(app):
    none = make_donor("O+")
    sms_only = _opt(make_donor("O+"), sms=True)
    all3 = _opt(make_donor("O+"), sms=True, wa=True, email=True)
    assert channels.alert_donor(none, "hello", "k1") == []
    assert channels.alert_donor(sms_only, "hello", "k2") == ["sms"]
    assert sorted(channels.alert_donor(all3, "hello", "k3")) == ["email", "sms", "whatsapp"]
    db.session.commit()
    assert _outbox(user_id=none.id) == []
    assert {m.to_address for m in _outbox(user_id=all3.id, channel="sms")} == {"+923001110000"}


def test_alerts_are_not_queued_twice(app):
    d = _opt(make_donor("O+"), sms=True)
    assert channels.alert_donor(d, "hello", "same") == ["sms"]
    assert channels.alert_donor(d, "hello", "same") == []
    db.session.commit()
    assert OutboxMessage.query.count() == 1


def test_delivery_uses_the_provider_and_marks_sent(app):
    sent = []
    app.extensions["channel_sender"] = lambda ch, to, body: sent.append((ch, to, body))
    d = _opt(make_donor("O+"), sms=True, wa=True)
    channels.alert_donor(d, "Need O+ near Sukkur", "k")
    db.session.commit()
    assert channels.deliver_pending() == {"sent": 2, "failed": 0, "skipped": 0}
    assert sorted(sent) == [("sms", "+923001110000", "Need O+ near Sukkur"),
                            ("whatsapp", "+923001110000", "Need O+ near Sukkur")]
    assert all(m.status == "sent" and m.sent_at for m in OutboxMessage.query.all())
    assert channels.deliver_pending()["sent"] == 0                      # nothing is sent twice


def test_without_a_provider_nothing_is_sent(app):
    d = _opt(make_donor("O+"), sms=True)
    channels.alert_donor(d, "hi", "k")
    db.session.commit()
    assert app.config["NOTIFY_PROVIDER"] == "none"
    assert channels.deliver_pending()["skipped"] == 1
    assert OutboxMessage.query.one().status == "skipped"


def test_failures_retry_then_give_up(app):
    def boom(*a):
        raise ConnectionError("down")
    app.extensions["channel_sender"] = boom
    d = _opt(make_donor("O+"), sms=True)
    channels.alert_donor(d, "hi", "k")
    db.session.commit()
    for _ in range(channels.MAX_ATTEMPTS - 1):
        assert channels.deliver_pending()["failed"] == 0
    assert channels.deliver_pending()["failed"] == 1
    row = OutboxMessage.query.one()
    assert row.status == "failed" and row.attempts == 3 and row.last_error == "ConnectionError"


def test_push_goes_to_every_browser_and_prunes_gone_ones(app):
    d = make_donor("O+")
    for n in (1, 2):
        db.session.add(PushSubscription(role="donor", user_id=d.id, endpoint=f"https://push.example/{n}",
                                        p256dh="k", auth="a"))
    db.session.commit()
    calls = []

    class Gone(Exception):
        gone = True

    def sender(info, payload):
        calls.append(info["endpoint"])
        if info["endpoint"].endswith("/2"):
            raise Gone()
    app.extensions["push_sender"] = sender
    assert channels.alert_donor(d, "A blood request matches your group", "p") == ["push"]
    db.session.commit()
    assert channels.deliver_pending()["sent"] == 1
    assert sorted(calls) == ["https://push.example/1", "https://push.example/2"]
    assert PushSubscription.query.count() == 1


# -------------------------------------------------- who is alerted about what
def test_only_critical_requests_use_sms_whatsapp_and_push(app, scene):
    sms = _opt(make_donor("O+"), sms=True)
    notifications.notify_matching_donors(scene.request)                   # Normal
    assert OutboxMessage.query.count() == 0
    crit = make_request(scene.patient, scene.hospital, urgency="Critical")
    notifications.notify_matching_donors(crit)
    assert [m.user_id for m in OutboxMessage.query.all()] == [sms.id]
    assert Notification.query.filter_by(donor_id=sms.id, request_id=crit.id).count() == 1


def test_outbox_is_erased_with_the_account(app):
    d = _opt(make_donor("O+"), sms=True)
    db.session.add(PushSubscription(role="donor", user_id=d.id, endpoint="https://p/1", p256dh="k", auth="a"))
    channels.alert_donor(d, "hi", "k")
    db.session.commit()
    privacy.erase_donor(d)
    assert OutboxMessage.query.filter_by(user_id=d.id).count() == 0 and PushSubscription.query.count() == 0


# ------------------------------------------------------------------ reminders
def _scheduled(scene, donor, when):
    resp = allocation.pledge(donor, scene.request.id, consent_to_share=True)
    allocation.schedule_appointment(scene.hospital, resp.id, when)
    return resp


def test_reminder_24h_is_sent_once(app, scene):
    _opt(scene.donors[0], sms=True)
    now = datetime.utcnow().replace(microsecond=0)
    resp = _scheduled(scene, scene.donors[0], now + timedelta(hours=20))
    assert jobs.send_reminders(now) == 1
    assert jobs.send_reminders(now + timedelta(minutes=30)) == 0
    assert Notification.query.filter(Notification.message.like("Reminder:%")).count() == 1
    sms = _outbox(channel="sms")
    assert len(sms) == 1 and "Test Hospital" in sms[0].body and "photo ID" in sms[0].body
    assert resp.reminder_24h_at is not None and resp.reminder_2h_at is None


def test_second_reminder_comes_two_hours_before(app, scene):
    now = datetime.utcnow().replace(microsecond=0)
    resp = _scheduled(scene, scene.donors[0], now + timedelta(hours=20))
    jobs.send_reminders(now)
    assert jobs.send_reminders(now + timedelta(hours=19)) == 1
    assert Notification.query.filter(Notification.message.like("Reminder:%")).count() == 2


def test_appointment_made_close_in_time_gets_one_reminder_not_two(app, scene):
    now = datetime.utcnow().replace(microsecond=0)
    _scheduled(scene, scene.donors[0], now + timedelta(hours=1))
    assert jobs.send_reminders(now) == 1
    assert Notification.query.filter(Notification.message.like("Reminder:%")).count() == 1


def test_no_reminders_far_ahead_or_for_cancelled_offers(app, scene):
    now = datetime.utcnow().replace(microsecond=0)
    far = _scheduled(scene, scene.donors[0], now + timedelta(days=3))
    gone = _scheduled(scene, scene.donors[1], now + timedelta(hours=5))
    allocation.cancel_response(gone.id, "donor", scene.donors[1].id)
    assert jobs.send_reminders(now) == 0
    assert far.reminder_24h_at is None


def test_rescheduling_sends_a_fresh_reminder(app, scene):
    now = datetime.utcnow().replace(microsecond=0)
    resp = _scheduled(scene, scene.donors[0], now + timedelta(hours=20))
    jobs.send_reminders(now)
    resp.reminder_24h_at = None                                         # a new time resets the markers
    allocation.schedule_appointment(scene.hospital, resp.id, now + timedelta(hours=21))
    assert jobs.send_reminders(now) == 1


# ----------------------------------------------------------------- escalation
@pytest.fixture
def urgent(app):
    hospital, patient = make_hospital(city="Sukkur"), make_patient()
    req = make_request(patient, hospital, group="O+", units=2, urgency="Critical")
    req.approved_at = datetime.utcnow() - timedelta(minutes=40)
    near = _opt(make_donor("O+", city="Sukkur"), sms=True)
    mid = _opt(make_donor("O-", city="Khairpur"), sms=True)            # about 30 km away
    far = _opt(make_donor("O+", city="Karachi"), sms=True)             # about 370 km away
    db.session.commit()
    return type("U", (), dict(hospital=hospital, patient=patient, req=req, near=near, mid=mid, far=far))


def test_level_one_widens_to_donors_within_50_km_only(app, urgent):
    assert jobs.escalate_requests() == 1
    alerted = {n.donor_id for n in Notification.query.filter(Notification.message.like("Still urgent%"))}
    assert alerted == {urgent.near.id, urgent.mid.id}
    assert {m.user_id for m in _outbox(channel="sms")} == {urgent.near.id, urgent.mid.id}
    assert urgent.req.escalation_level == 1 and urgent.req.escalated_at is not None


def test_level_two_after_two_hours_reaches_everyone_compatible(app, urgent):
    jobs.escalate_requests()
    urgent.req.approved_at = datetime.utcnow() - timedelta(minutes=130)
    db.session.commit()
    assert jobs.escalate_requests() == 1
    assert {n.donor_id for n in Notification.query.filter(Notification.message.like("Still urgent%"))} == \
        {urgent.near.id, urgent.mid.id, urgent.far.id}
    assert urgent.req.escalation_level == 2


def test_escalation_is_idempotent_and_tells_hospital_and_patient(app, urgent):
    jobs.escalate_requests()
    assert jobs.escalate_requests() == 0
    from models import AccountNotification
    msgs = AccountNotification.query.filter(AccountNotification.message.like("%widened%")).all()
    assert {(m.role, m.user_id) for m in msgs} == {("hospital", urgent.hospital.id), ("patient", urgent.patient.id)}
    assert AuditLog.query.filter_by(action="request.escalated").count() == 1


def test_no_escalation_when_someone_already_offered(app, urgent):
    allocation.pledge(urgent.near, urgent.req.id, consent_to_share=True)
    assert jobs.escalate_requests() == 0


def test_no_escalation_for_normal_requests_or_too_early(app, urgent):
    urgent.req.urgency = "Normal"
    db.session.commit()
    assert jobs.escalate_requests() == 0
    urgent.req.urgency = "Urgent"
    urgent.req.approved_at = datetime.utcnow() - timedelta(minutes=5)
    db.session.commit()
    assert jobs.escalate_requests() == 0


def test_no_escalation_after_the_request_expired_or_closed(app, urgent):
    urgent.req.expiry_date = datetime.utcnow() - timedelta(hours=1)
    db.session.commit()
    assert jobs.escalate_requests() == 0


# ------------------------------------------------------- distance in matching
def _scores(req):
    return {m.donor.id: m for m in rank_donors(req)}


def test_closer_donors_rank_higher_and_say_how_far(app):
    hospital, patient = make_hospital(city="Sukkur"), make_patient()
    req = make_request(patient, hospital, group="O+", location="Sukkur")
    near = make_donor("O+", city="Khairpur")
    far = make_donor("O+", city="Lahore")
    s = _scores(req)
    assert s[near.id].score > s[far.id].score
    assert any("km from the hospital" in r for r in s[near.id].reasons)


def test_exact_area_beats_city_centre(app):
    hospital, patient = make_hospital(city="Karachi"), make_patient()
    hospital.lat, hospital.lng = 24.90, 67.08
    db.session.commit()
    req = make_request(patient, hospital, group="O+", location="Karachi")
    a, b = make_donor("O+", city="Karachi"), make_donor("O+", city="Karachi")
    b.area_lat, b.area_lng = 24.90, 67.08
    db.session.commit()
    s = _scores(req)
    assert s[b.id].score >= s[a.id].score


def test_available_now_boost_and_no_show_penalty(app, scene):
    a, b, c = (make_donor("O+") for _ in range(3))
    b.available_until = datetime.utcnow() + timedelta(hours=3)
    resp = DonationResponse(donor_id=c.id, request_id=scene.request.id, response_status="Cancelled",
                            no_show_at=datetime.utcnow(), contact_consent_at=datetime.utcnow())
    db.session.add(resp)
    db.session.commit()
    s = _scores(make_request(scene.patient, scene.hospital, group="O+"))
    assert s[b.id].score == s[a.id].score + app.config["MATCH_WEIGHTS"]["available_now"]
    assert s[c.id].score == s[a.id].score + app.config["MATCH_WEIGHTS"]["no_show_penalty"]
    assert any("missed appointment" in r for r in s[c.id].reasons)


def test_expired_available_now_gives_no_boost(app, scene):
    a, b = make_donor("O+"), make_donor("O+")
    b.available_until = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    s = _scores(make_request(scene.patient, scene.hospital, group="O+"))
    assert s[a.id].score == s[b.id].score


def test_geo_helpers():
    assert round(geo.haversine_km((27.7052, 68.8574), (24.8607, 67.0011))) in range(355, 385)
    assert geo.city_point("  SUKKUR ") == geo.city_point("sukkur") and geo.city_point("Atlantis") is None
    assert geo.clean_area("27.70523", "68.85741") == (27.71, 68.86)
    for bad in (("x", 1), (91, 0), (0, 181), (None, None), ("nan", 0)):
        assert geo.clean_area(*bad) == (None, None)


# -------------------------------------------------- donor controls + PWA + CLI
def _donor_client(app):
    d = make_donor("O+")
    c = app.test_client(); login(c, d, "donor")
    return d, c


def test_available_now_buttons(app):
    d, c = _donor_client(app)
    c.post("/donor/available-now", data={"hours": "6"})
    db.session.expire_all()
    assert timedelta(hours=5) < d.available_until - datetime.utcnow() <= timedelta(hours=6)
    c.post("/donor/available-now", data={"hours": "999"})                # anything else clears it
    db.session.expire_all()
    assert d.available_until is None


def test_area_is_rounded_validated_and_removable(app):
    d, c = _donor_client(app)
    c.post("/donor/area", data={"lat": "27.705234", "lng": "68.857411"})
    db.session.expire_all()
    assert (d.area_lat, d.area_lng) == (27.71, 68.86)
    c.post("/donor/area", data={"lat": "abc", "lng": "1"})
    db.session.expire_all()
    assert d.area_lat == 27.71                                           # bad input changes nothing
    c.post("/donor/area", data={"clear": "1"})
    db.session.expire_all()
    assert d.area_lat is None


def test_sms_and_whatsapp_choices_are_saved_with_consent_records(app):
    from models import ConsentRecord
    d, c = _donor_client(app)
    c.post("/account/preferences", data={"sms_opt_in": "on", "whatsapp_opt_in": "on"})
    db.session.expire_all()
    assert d.sms_opt_in and d.whatsapp_opt_in
    c.post("/account/preferences", data={})
    db.session.expire_all()
    assert not d.sms_opt_in
    purposes = {r.purpose for r in ConsentRecord.query.filter_by(subject_id=d.id)}
    assert {"sms_alerts", "whatsapp_alerts"} <= purposes


def test_push_subscription_endpoints(app):
    d, c = _donor_client(app)
    good = {"endpoint": "https://fcm.example/abc", "keys": {"p256dh": "k", "auth": "a"}}
    assert c.post("/push/subscribe", json=good).status_code == 201
    assert c.post("/push/subscribe", json=good).status_code == 201          # same browser twice: one row
    assert PushSubscription.query.count() == 1
    for bad in ({"endpoint": "http://insecure/x", "keys": {"p256dh": "k", "auth": "a"}}, {"endpoint": "https://x"}, {}):
        assert c.post("/push/subscribe", json=bad).status_code == 400
    other = app.test_client(); login(other, make_donor("A+"), "donor")
    other.post("/push/unsubscribe", json={"endpoint": good["endpoint"]})     # someone else cannot remove it
    assert PushSubscription.query.count() == 1
    c.post("/push/unsubscribe", json={"endpoint": good["endpoint"]})
    assert PushSubscription.query.count() == 0
    assert app.test_client().post("/push/subscribe", json=good).status_code == 302


def test_push_key_is_empty_until_configured(app):
    _, c = _donor_client(app)
    assert c.get("/push/key").get_json() == {"key": ""}
    app.config.update(VAPID_PUBLIC_KEY="pub", VAPID_PRIVATE_KEY="priv", VAPID_SUBJECT="mailto:a@b.c")
    assert c.get("/push/key").get_json() == {"key": "pub"}


def test_installable_app_files(client):
    m = client.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.get_json()["display"] == "standalone"
    assert {i["sizes"] for i in m.get_json()["icons"]} == {"192x192", "512x512"}
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["Service-Worker-Allowed"] == "/" and "javascript" in sw.mimetype
    assert client.get("/offline").status_code == 200
    assert client.get("/static/images/pwa/icon-512.png").status_code == 200


def test_jobs_command_runs_every_job(app):
    out = app.test_cli_runner().invoke(args=["jobs"]).output
    for name in ("expire", "reminders", "escalate", "deliver", "cleanup"):
        assert f"{name}:" in out
    only = app.test_cli_runner().invoke(args=["jobs", "--only", "deliver"]).output
    assert "deliver:" in only and "reminders:" not in only

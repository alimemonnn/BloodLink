"""Health reports, "I donated" checks, hospital emergencies, camp attendance, and cancel / withdraw."""
import json
from datetime import date, datetime, timedelta

import pytest

from conftest import PASSWORD, login, make_donor, make_hospital, make_patient, make_request
from models import (Admin, Camp, CampSignup, DonationResponse, Notification, OutboxMessage, ScreeningReport,
                    AccountNotification, ChatMessage, db)
from utils import allocation, badges, camps, emergency, privacy, screening, trust, verification
from utils.maintenance import retention_cleanup


def _c(app, user, role):
    c = app.test_client(); login(c, user, role)
    return c


@pytest.fixture
def offer(scene):
    return allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)


def _screen(**over):
    d = {"outcome": "Temporarily deferred", "reason": "Low haemoglobin", "deferral_days": "30", "hemoglobin": "11.2",
         "systolic": "120", "diastolic": "80", "pulse": "72", "temperature_c": "36.8", "weight_kg": "62",
         "message_to_donor": "Please eat iron-rich food and come back.", "internal_note": "PRIVATE staff remark",
         "shared_with_donor": "on"}
    d.update(over)
    return d


# =============================================================== existing: cancel and withdraw
def test_patient_can_cancel_a_request_and_offering_donors_are_told(app, scene, offer):
    r = _c(app, scene.patient, "patient").post(f"/patient/requests/{scene.request.id}/cancel", data={"reason": "Found a donor"})
    assert r.status_code == 302
    db.session.expire_all()
    assert scene.request.status == "Cancelled"
    assert db.session.get(DonationResponse, offer.id).response_status == "Cancelled"
    assert Notification.query.filter(Notification.donor_id == scene.donors[0].id, Notification.message.like("%closed%")).count() == 1
    assert _c(app, make_patient(), "patient").post(f"/patient/requests/{scene.request.id}/cancel").status_code in (302, 403)


def test_donor_can_withdraw_after_saying_i_can_donate(app, scene, offer):
    r = _c(app, scene.donors[0], "donor").post(f"/donor/history/{offer.id}/cancel", data={"reason": "Sick today"})
    assert r.status_code == 302
    db.session.expire_all()
    assert db.session.get(DonationResponse, offer.id).response_status == "Cancelled"
    assert AccountNotification.query.filter_by(role="hospital", user_id=scene.hospital.id).count() >= 1
    assert scene.request.units_confirmed == 0
    again = allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)      # can offer again later
    assert again.id == offer.id and again.response_status == "Interested"


# ================================================================== screening reports
def test_hospital_records_a_deferral_donor_reads_why_and_matching_skips_them(app, scene, offer):
    h = _c(app, scene.hospital, "hospital")
    assert h.get(f"/hospital/responses/{offer.id}/screening").status_code == 200
    r = h.post(f"/hospital/responses/{offer.id}/screening", data=_screen())
    assert r.status_code == 302
    db.session.expire_all()
    rep = ScreeningReport.query.one()
    assert rep.hospital_id == scene.hospital.id and rep.deferral_until == date.today() + timedelta(days=30)
    assert db.session.get(DonationResponse, offer.id).response_status == "Ineligible"          # offer closed
    assert scene.donors[0].deferred_until == rep.deferral_until
    page = _c(app, scene.donors[0], "donor").get("/donor/health").get_data(as_text=True)
    assert "asked you to wait" in page and "Low haemoglobin" in page and "iron-rich" in page
    assert "PRIVATE staff remark" not in page
    detail = _c(app, scene.donors[0], "donor").get(f"/donor/health/{rep.id}").get_data(as_text=True)
    assert "11.2" in detail and "PRIVATE staff remark" not in detail
    from utils.matching import rank_donors
    assert scene.donors[0].id not in {m.donor.id for m in rank_donors(scene.request)}


def test_notifications_never_contain_health_details(app, scene, offer):
    _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{offer.id}/screening", data=_screen())
    text = " ".join(n.message for n in Notification.query.filter_by(donor_id=scene.donors[0].id))
    assert "haemoglobin" not in text.lower() and "11.2" not in text and "My health" in text


def test_unshared_reports_are_hidden_from_the_donor(app, scene, offer):
    _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{offer.id}/screening", data=_screen(shared_with_donor=""))
    rep = ScreeningReport.query.one()
    c = _c(app, scene.donors[0], "donor")
    assert c.get(f"/donor/health/{rep.id}").status_code == 404 and c.get(f"/donor/health/{rep.id}.pdf").status_code == 404
    assert "Low haemoglobin" not in c.get("/donor/health").get_data(as_text=True).split("Health check reports")[1].split("My confirmed")[0]
    assert Notification.query.filter(Notification.message.like("%health check report%")).count() == 0


def test_only_the_donor_and_the_owning_hospital_can_reach_a_report(app, scene, offer):
    _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{offer.id}/screening", data=_screen())
    rep = ScreeningReport.query.one()
    assert _c(app, scene.donors[1], "donor").get(f"/donor/health/{rep.id}").status_code == 404
    assert _c(app, scene.patient, "patient").get(f"/donor/health/{rep.id}").status_code == 403
    assert app.test_client().get(f"/donor/health/{rep.id}").status_code == 302
    other = _c(app, make_hospital(), "hospital")
    assert other.get(f"/hospital/responses/{offer.id}/screening").status_code == 404
    assert other.post(f"/hospital/responses/{offer.id}/screening", data=_screen()).status_code == 404
    a = Admin(name="A", email="adm-h@example.com"); a.set_password(PASSWORD); db.session.add(a); db.session.commit()
    for url in (f"/donor/health/{rep.id}", "/donor/health"):
        assert _c(app, a, "admin").get(url).status_code == 403


@pytest.mark.parametrize("bad", [{"outcome": ""}, {"outcome": "Hacked"}, {"hemoglobin": "99"}, {"hemoglobin": "abc"}, {"systolic": "5"},
                                  {"pulse": "900"}, {"temperature_c": "50"}, {"weight_kg": "1"}, {"reason": ""}, {"deferral_days": "0"},
                                  {"deferral_days": "9999"}, {"reason": "Made up"}])
def test_invalid_screening_input_is_refused(app, scene, offer, bad):
    r = _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{offer.id}/screening", data=_screen(**bad))
    assert r.status_code == 400 and ScreeningReport.query.count() == 0
    db.session.expire_all()
    assert db.session.get(DonationResponse, offer.id).response_status == "Interested"


def test_a_fit_report_keeps_the_offer_open_and_can_be_edited(app, scene, offer):
    h = _c(app, scene.hospital, "hospital")
    h.post(f"/hospital/responses/{offer.id}/screening", data=_screen(outcome="Fit to donate", reason="", deferral_days="", message_to_donor="All good"))
    db.session.expire_all()
    assert db.session.get(DonationResponse, offer.id).response_status == "Interested" and ScreeningReport.query.one().fit
    h.post(f"/hospital/responses/{offer.id}/screening", data=_screen(outcome="Fit to donate", reason="", deferral_days="", message_to_donor="Updated"))
    assert ScreeningReport.query.count() == 1 and ScreeningReport.query.one().message_to_donor == "Updated"


def test_eligibility_states(app, scene):
    d = scene.donors[0]
    assert screening.donor_eligibility(d)["state"] == "eligible"
    d.last_donation_date = date.today() - timedelta(days=10); db.session.commit()
    assert screening.donor_eligibility(d)["state"] == "resting" and screening.donor_eligibility(d)["days"] > 0
    d.last_donation_date = None
    db.session.add(ScreeningReport(donor_id=d.id, hospital_id=scene.hospital.id, outcome="Not eligible", reason="Taking medication",
                                   message_to_donor="Please speak to us", shared_with_donor=True))
    db.session.commit()
    e = screening.donor_eligibility(d)
    assert e["state"] == "not_eligible" and e["reason"] == "Taking medication"


def test_report_pdf_and_deletion_and_export(app, scene, offer):
    _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{offer.id}/screening", data=_screen())
    rep = ScreeningReport.query.one()
    pdf = _c(app, scene.donors[0], "donor").get(f"/donor/health/{rep.id}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    exported = json.dumps(privacy.export_data("donor", scene.donors[0]), default=str)
    privacy.erase_donor(scene.donors[0])
    assert ScreeningReport.query.count() == 0


def test_old_reports_are_deleted_by_the_retention_job(app, scene, offer):
    _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{offer.id}/screening", data=_screen())
    rep = ScreeningReport.query.one()
    rep.created_at = datetime.utcnow() - timedelta(days=app.config["REPORT_RETENTION_DAYS"] + 1)
    db.session.commit()
    assert retention_cleanup(app.config)["reports_deleted"] == 1


def test_audit_log_records_that_a_report_was_written_but_not_its_contents(app, scene, offer):
    from models import AuditLog
    _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{offer.id}/screening", data=_screen())
    row = AuditLog.query.filter_by(action="screening.saved").one()
    assert "haemoglobin" not in (row.detail or "").lower() and "11.2" not in (row.detail or "")


# ================================================================ "I donated" claims
def test_a_claim_asks_the_hospital_to_check_and_never_counts_blood(app, scene, offer):
    c = _c(app, scene.donors[0], "donor")
    assert c.post(f"/donor/responses/{offer.id}/claim").status_code == 302
    db.session.expire_all()
    assert offer.donor_claimed_at is not None and scene.request.units_confirmed == 0
    assert badges.summary(scene.donors[0])["donations"] == 0
    assert AccountNotification.query.filter(AccountNotification.role == "hospital", AccountNotification.message.like("%says they donated%")).count() == 1
    assert any("says they have donated" in m.body for m in ChatMessage.query.filter_by(kind="event"))
    h = _c(app, scene.hospital, "hospital")
    assert "Donor says they donated" in h.get(f"/hospital/requests/{scene.request.id}").get_data(as_text=True)
    assert scene.donors[0].name in h.get("/hospital/dashboard").get_data(as_text=True)
    allocation.confirm_donation(scene.hospital, offer.id)                       # only this counts blood
    db.session.expire_all()
    assert scene.request.units_confirmed == 1 and badges.summary(scene.donors[0])["donations"] == 1


def test_a_claim_can_be_sent_once_and_only_for_your_own_open_offer(app, scene, offer):
    c = _c(app, scene.donors[0], "donor")
    c.post(f"/donor/responses/{offer.id}/claim")
    c.post(f"/donor/responses/{offer.id}/claim")
    assert AccountNotification.query.filter(AccountNotification.message.like("%says they donated%")).count() == 1
    other = _c(app, scene.donors[1], "donor")
    other.post(f"/donor/responses/{offer.id}/claim")                            # not their offer
    with pytest.raises(verification.ClaimError):
        verification.claim_donation(scene.donors[1], offer.id)
    allocation.cancel_response(offer.id, "donor", scene.donors[0].id)
    with pytest.raises(verification.ClaimError):
        verification.claim_donation(scene.donors[0], offer.id)                  # closed offers cannot be claimed


def test_the_hospital_can_say_no_record_found(app, scene, offer):
    _c(app, scene.donors[0], "donor").post(f"/donor/responses/{offer.id}/claim")
    h = _c(app, scene.hospital, "hospital")
    h.post(f"/hospital/responses/{offer.id}/dispute-claim", data={"note": "We have no record today"})
    db.session.expire_all()
    assert offer.claim_disputed_at and offer.claim_note == "We have no record today"
    page = _c(app, scene.donors[0], "donor").get("/donor/history").get_data(as_text=True)
    assert "We have no record today" in page and "I donated" not in page
    with pytest.raises(verification.ClaimError):
        verification.claim_donation(scene.donors[0], offer.id)                  # cannot just claim again
    assert _c(app, make_hospital(), "hospital").post(f"/hospital/responses/{offer.id}/dispute-claim").status_code == 404


def test_history_shows_the_i_donated_button_for_open_offers(app, scene, offer):
    page = _c(app, scene.donors[0], "donor").get("/donor/history").get_data(as_text=True)
    assert "I donated" in page and f"/donor/responses/{offer.id}/claim" in page


# ============================================================== hospital emergency request
def test_hospital_posts_an_emergency_request_that_is_live_at_once(app, scene):
    sms = make_donor("O-"); sms.sms_opt_in = True; db.session.commit()
    h = _c(app, scene.hospital, "hospital")
    assert h.get("/hospital/emergency").status_code == 200
    r = h.post("/hospital/emergency", data={"blood_group_required": "O-", "units_required": "3", "urgency": "Critical", "hours": "12",
                                            "patient_label": "A. K.", "description": "Casualty, ask for Dr Shah"})
    assert r.status_code == 302
    from models import BloodRequest
    req = BloodRequest.query.filter_by(source="hospital").one()
    assert req.status == "Approved" and req.units_required == 3 and req.urgency == "Critical" and req.hospital_id == scene.hospital.id
    assert req.approved_at and 11 * 3600 < (req.expiry_date - datetime.utcnow()).total_seconds() <= 12 * 3600
    assert Notification.query.filter_by(request_id=req.id).count() >= 1          # donors alerted now
    assert [m.user_id for m in OutboxMessage.query.filter_by(channel="sms")] == [sms.id]     # critical: SMS too


def test_emergency_requests_work_with_every_screen_that_shows_a_patient(app, scene, client):
    req, _ = emergency.create(scene.hospital, {"blood_group_required": "A+", "units_required": "2", "hours": "24"})
    assert req.patient.is_active is False and req.patient_name == "Hospital emergency"
    assert _c(app, scene.hospital, "hospital").get(f"/hospital/requests/{req.id}").status_code == 200
    assert "Hospital emergency" in client.get("/emergency").get_data(as_text=True)
    a = Admin(name="A", email="adm-e@example.com"); a.set_password(PASSWORD); db.session.add(a); db.session.commit()
    assert _c(app, a, "admin").get(f"/admin/requests/{req.id}").status_code == 200
    assert client.get("/api/v1/requests").get_json()["items"][0]["patient"] in ("H. E.", "Hospital emergency")


def test_nobody_can_log_in_as_the_walk_in_patient(app, scene):
    req, _ = emergency.create(scene.hospital, {"blood_group_required": "A+", "units_required": "1"})
    c = app.test_client()
    r = c.post("/login", data={"email": req.patient.email, "password": "anything", "role": "patient"})
    assert r.status_code in (200, 302) and c.get("/patient/dashboard").status_code == 302


def test_one_walk_in_record_per_hospital_and_chat_still_works(app, scene):
    a, _ = emergency.create(scene.hospital, {"blood_group_required": "O+", "units_required": "1"})
    b, _ = emergency.create(scene.hospital, {"blood_group_required": "O+", "units_required": "1"})
    assert a.patient_id == b.patient_id and emergency.walkin_patient(make_hospital()).id != a.patient_id
    offer = allocation.pledge(scene.donors[0], a.id, consent_to_share=True)
    r = _c(app, scene.donors[0], "donor").post(f"/messages/{offer.id}/send", json={"body": "On my way"})
    assert r.status_code == 201
    page = _c(app, scene.hospital, "hospital").get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "the patient's family" not in page and "On my way" in page


@pytest.mark.parametrize("bad", [{"blood_group_required": "Z+"}, {"blood_group_required": ""}, {"units_required": "0"}, {"units_required": "99"},
                                  {"units_required": "x"}])
def test_emergency_validation(app, scene, bad):
    form = {"blood_group_required": "O+", "units_required": "2"}; form.update(bad)
    r = _c(app, scene.hospital, "hospital").post("/hospital/emergency", data=form)
    assert r.status_code == 400
    from models import BloodRequest
    assert BloodRequest.query.filter_by(source="hospital").count() == 0


def test_only_hospitals_can_post_emergencies(app, scene):
    assert _c(app, scene.donors[0], "donor").get("/hospital/emergency").status_code == 403
    assert _c(app, scene.patient, "patient").post("/hospital/emergency", data={}).status_code == 403
    assert app.test_client().get("/hospital/emergency").status_code == 302


# ===================================================================== camps
def _camp(hospital, hours_ahead=1, capacity=2, **kw):
    c = Camp(hospital_id=hospital.id, title="Blood Drive", venue="Hall", city=hospital.city,
             starts_at=datetime.utcnow() + timedelta(hours=hours_ahead), ends_at=datetime.utcnow() + timedelta(hours=hours_ahead + 4),
             capacity=capacity, **kw)
    db.session.add(c); db.session.commit()
    return c


def test_raising_capacity_promotes_the_waiting_list_and_edits_tell_everyone(app, scene):
    camp = _camp(scene.hospital, hours_ahead=48, capacity=1)
    a, b = scene.donors[0], scene.donors[1]
    camps.join(camp, a); sb = camps.join(camp, b)
    assert sb.status == "Waitlist"
    form = {"title": camp.title, "venue": "New hall", "city": camp.city, "capacity": "2",
            "starts_at": (camp.starts_at + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
            "ends_at": (camp.ends_at + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")}
    _c(app, scene.hospital, "hospital").post(f"/hospital/camps/{camp.id}/edit", data=form)
    db.session.expire_all()
    assert CampSignup.query.get(sb.id).status == "Signed up" and Camp.query.get(camp.id).venue == "New hall"
    assert Notification.query.filter(Notification.donor_id == a.id, Notification.message.like("%was updated%")).count() == 1
    assert _c(app, make_hospital(), "hospital").get(f"/hospital/camps/{camp.id}/edit").status_code == 404


def test_no_show_frees_a_place_for_the_waiting_list(app, scene):
    camp = _camp(scene.hospital, hours_ahead=1, capacity=1)
    first = camps.join(camp, scene.donors[0]); waiting = camps.join(camp, scene.donors[1])
    camps.record(scene.hospital, first.id, "no_show")
    db.session.expire_all()
    assert CampSignup.query.get(first.id).status == "No-show" and CampSignup.query.get(waiting.id).status == "Signed up"


def test_roster_opens_only_two_hours_before_and_only_for_the_owner(app, scene):
    far = _camp(scene.hospital, hours_ahead=30)
    s = camps.join(far, scene.donors[0])
    with pytest.raises(camps.CampError):
        camps.record(scene.hospital, s.id, "donated", 1)
    near = _camp(scene.hospital, hours_ahead=1)
    n = camps.join(near, scene.donors[1])
    with pytest.raises(camps.CampError):
        camps.record(make_hospital(), n.id, "donated", 1)
    assert _c(app, make_hospital(), "hospital").post(f"/hospital/camps/signups/{n.id}/record", data={"action": "donated"}).status_code == 404
    assert _c(app, scene.donors[0], "donor").get(f"/hospital/camps/{near.id}/roster").status_code == 403


def test_a_recorded_camp_donation_counts_everywhere(app, scene):
    camp = _camp(scene.hospital, hours_ahead=1)
    donor = scene.donors[0]
    s = camps.join(camp, donor)
    h = _c(app, scene.hospital, "hospital")
    h.post(f"/hospital/camps/signups/{s.id}/record", data={"action": "attended"})
    h.post(f"/hospital/camps/signups/{s.id}/record", data={"action": "donated", "units": "1"})
    db.session.expire_all()
    s = CampSignup.query.get(s.id)
    assert s.status == "Donated" and s.units == 1 and s.verified_by_hospital_id == scene.hospital.id
    assert donor.last_donation_date == date.today()
    summary = badges.summary(donor)
    assert summary["donations"] == 1 and summary["units"] == 1 and summary["badges"][0]["earned"] and not summary["can_donate_now"]
    page = _c(app, donor, "donor").get("/donor/health").get_data(as_text=True)
    assert "Camp: Blood Drive" in page and f"/donor/camp-certificate/{s.id}.pdf" in page
    pdf = _c(app, donor, "donor").get(f"/donor/camp-certificate/{s.id}.pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    code = trust.camp_certificate_code(s)
    assert code.startswith("BC-")
    anon = app.test_client()
    assert "Genuine" in anon.get(f"/verify/{code}").get_data(as_text=True)
    assert anon.get(f"/api/v1/certificates/{code}").get_json()["valid"] is True
    assert "not valid" in anon.get(f"/verify/BC-{s.id:05d}-DEADBEEF").get_data(as_text=True)
    with pytest.raises(camps.CampError):
        camps.record(scene.hospital, s.id, "donated", 1)                       # only once
    assert _c(app, scene.donors[1], "donor").get(f"/donor/camp-certificate/{s.id}.pdf").status_code == 404


def test_camp_units_are_capped_and_waitlisted_people_cannot_be_recorded(app, scene):
    camp = _camp(scene.hospital, hours_ahead=1, capacity=1)
    first = camps.join(camp, scene.donors[0]); waiting = camps.join(camp, scene.donors[1])
    with pytest.raises(camps.CampError):
        camps.record(scene.hospital, first.id, "donated", 5)
    with pytest.raises(camps.CampError):
        camps.record(scene.hospital, waiting.id, "donated", 1)


def test_camp_reminder_is_sent_once_the_day_before(app, scene):
    near, far = _camp(scene.hospital, hours_ahead=20), _camp(scene.hospital, hours_ahead=60)
    camps.join(near, scene.donors[0]); camps.join(far, scene.donors[1])
    assert camps.send_reminders() == 1 and camps.send_reminders() == 0
    assert Notification.query.filter(Notification.message.like("Reminder: \"Blood Drive\"%")).count() == 1


def test_camp_detail_calendar_and_cancelled_camps(app, scene, client):
    camp = _camp(scene.hospital, hours_ahead=48, description="Free screening")
    page = client.get(f"/camps/{camp.id}").get_data(as_text=True)
    assert "Free screening" in page and "Directions" in page and "Add to calendar" in page
    ics = client.get(f"/camps/{camp.id}.ics")
    assert ics.mimetype == "text/calendar" and "BEGIN:VEVENT" in ics.get_data(as_text=True)
    camp.is_cancelled = True; db.session.commit()
    assert client.get(f"/camps/{camp.id}").status_code == 404 and client.get(f"/camps/{camp.id}.ics").status_code == 404


def test_attended_donors_cannot_cancel_and_leaving_deletes_the_row(app, scene):
    camp = _camp(scene.hospital, hours_ahead=1)
    s = camps.join(camp, scene.donors[0])
    camps.record(scene.hospital, s.id, "attended")
    with pytest.raises(camps.CampError):
        camps.leave(camp.id, scene.donors[0])
    t = camps.join(camp, scene.donors[1])
    camps.leave(camp.id, scene.donors[1])
    assert CampSignup.query.get(t.id) is None


def test_camp_health_check_and_erasure(app, scene):
    camp = _camp(scene.hospital, hours_ahead=1)
    s = camps.join(camp, scene.donors[0])
    h = _c(app, scene.hospital, "hospital")
    assert h.post(f"/hospital/camps/signups/{s.id}/screening", data=_screen(outcome="Fit to donate", reason="", deferral_days="")).status_code == 302
    assert ScreeningReport.query.one().camp_signup_id == s.id
    assert _c(app, make_hospital(), "hospital").get(f"/hospital/camps/signups/{s.id}/screening").status_code == 404
    privacy.erase_donor(scene.donors[0])
    assert ScreeningReport.query.count() == 0 and CampSignup.query.count() == 0


def test_old_database_without_the_new_columns_is_upgraded(tmp_path):
    import sqlite3
    import app as app_module
    from config import TestingConfig
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE camp_signups (id INTEGER PRIMARY KEY, camp_id INTEGER NOT NULL, donor_id INTEGER NOT NULL, created_at DATETIME)")
    con.execute("INSERT INTO camp_signups VALUES (1, 1, 1, '2026-10-01 10:00:00')")
    con.commit(); con.close()

    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"
    a = app_module.create_app(Cfg)
    with a.app_context():
        cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(camp_signups)")}
        assert {"status", "units", "verified_at", "reminded_at", "checked_in_at"} <= cols
        assert sqlite3.connect(path).execute("select status, units from camp_signups").fetchone() == ("Signed up", 0)
        db.session.remove(); db.engine.dispose()

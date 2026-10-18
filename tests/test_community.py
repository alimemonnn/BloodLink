"""Blood stock, donation camps, analytics, CSV exports and donor badges."""
from datetime import date, datetime, timedelta

import pytest

from conftest import login, make_donor, make_hospital, make_patient, make_request
from models import Admin, BloodStock, Camp, CampSignup, Notification, db
from conftest import PASSWORD
from utils import allocation, analytics, badges, privacy


def _c(app, user, role):
    c = app.test_client(); login(c, user, role)
    return c


def _admin(app):
    a = Admin(name="Admin Person", email="admin-c@example.com"); a.set_password(PASSWORD)
    db.session.add(a); db.session.commit()
    return _c(app, a, "admin")


def _future(hours):
    return (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")


# ---------------------------------------------------------------------- stock
def test_hospital_saves_stock_and_public_sees_it(app, client):
    h = make_hospital(city="Sukkur")
    c = _c(app, h, "hospital")
    r = c.post("/hospital/stock", data={"units_O+": "12", "units_A-": "1"})
    assert r.status_code == 302
    assert {(s.blood_group, s.units) for s in BloodStock.query} == {("O+", 12), ("A-", 1)}
    page = client.get("/stock").get_data(as_text=True)
    assert h.hospital_name in page and "Self-reported" in page and "low" in page       # A- has 1 unit
    assert h.hospital_name not in client.get("/stock?city=Lahore").get_data(as_text=True)


def test_stock_updates_in_place_and_rejects_bad_numbers(app):
    h = make_hospital()
    c = _c(app, h, "hospital")
    c.post("/hospital/stock", data={"units_O+": "5"})
    c.post("/hospital/stock", data={"units_O+": "9"})
    assert BloodStock.query.count() == 1 and BloodStock.query.one().units == 9
    c.post("/hospital/stock", data={"units_B+": "-3", "units_AB+": "abc", "units_O-": "99999"})
    assert BloodStock.query.count() == 1                                   # nothing saved on any error


def test_unverified_hospitals_are_not_listed_and_other_roles_are_blocked(app, client):
    h = make_hospital(verified=False)
    db.session.add(BloodStock(hospital_id=h.id, blood_group="O+", units=3)); db.session.commit()
    assert h.hospital_name not in client.get("/stock").get_data(as_text=True)
    assert _c(app, make_donor("O+"), "donor").get("/hospital/stock").status_code == 403


# ---------------------------------------------------------------------- camps
def _camp_form(**over):
    d = {"title": "Eid blood drive", "venue": "Civil Hospital lawn", "city": "Sukkur", "capacity": "2",
         "starts_at": _future(48), "ends_at": _future(52), "description": "Bring ID"}
    d.update(over)
    return d


def test_hospital_creates_a_camp_and_local_donors_are_told(app):
    h = make_hospital(city="Sukkur")
    near, far = make_donor("O+", city="Sukkur"), make_donor("O+", city="Lahore")
    r = _c(app, h, "hospital").post("/hospital/camps", data=_camp_form())
    assert r.status_code == 302 and Camp.query.count() == 1
    assert Notification.query.filter(Notification.donor_id == near.id, Notification.message.like("Donation camp%")).count() == 1
    assert Notification.query.filter_by(donor_id=far.id).count() == 0


@pytest.mark.parametrize("bad", [{"title": "x"}, {"venue": ""}, {"capacity": "0"}, {"capacity": "999999"},
                                  {"starts_at": _future(-5)}, {"ends_at": _future(40)}, {"ends_at": _future(24 * 10)},
                                  {"starts_at": "nope"}])
def test_invalid_camps_are_refused(app, bad):
    _c(app, make_hospital(), "hospital").post("/hospital/camps", data=_camp_form(**bad))
    assert Camp.query.count() == 0


def test_donor_signs_up_leaves_and_capacity_is_enforced(app, client):
    h = make_hospital()
    _c(app, h, "hospital").post("/hospital/camps", data=_camp_form(capacity="2"))
    camp = Camp.query.one()
    d1, d2, d3 = (make_donor("O+") for _ in range(3))
    for d in (d1, d2, d3):
        _c(app, d, "donor").post(f"/camps/{camp.id}/join")
    assert CampSignup.query.count() == 2                                    # the third found it full
    _c(app, d1, "donor").post(f"/camps/{camp.id}/join")                    # again: still one row
    assert CampSignup.query.filter_by(donor_id=d1.id).count() == 1
    _c(app, d1, "donor").post(f"/camps/{camp.id}/leave")
    assert CampSignup.query.count() == 1
    assert "Eid blood drive" in client.get("/camps").get_data(as_text=True)
    assert client.post(f"/camps/{camp.id}/join").status_code == 302          # anonymous: sent to log in


def test_only_the_owner_can_cancel_and_signups_are_told(app):
    h = make_hospital()
    _c(app, h, "hospital").post("/hospital/camps", data=_camp_form())
    camp = Camp.query.one()
    d = make_donor("O+")
    _c(app, d, "donor").post(f"/camps/{camp.id}/join")
    assert _c(app, make_hospital(), "hospital").post(f"/hospital/camps/{camp.id}/cancel").status_code == 404
    _c(app, h, "hospital").post(f"/hospital/camps/{camp.id}/cancel")
    db.session.expire_all()
    assert camp.is_cancelled
    assert Notification.query.filter(Notification.donor_id == d.id, Notification.message.like("%cancelled%")).count() == 1
    assert "Eid blood drive" not in app.test_client().get("/camps").get_data(as_text=True)


def test_camp_signups_do_not_leak_contact_details_without_consent(app):
    h = make_hospital()
    _c(app, h, "hospital").post("/hospital/camps", data=_camp_form())
    camp = Camp.query.one()
    quiet, open_ = make_donor("O+", share=False), make_donor("A+", share=True)
    quiet.phone, open_.phone = "0311-QUIET-111", "0322-OPEN-2222"
    db.session.commit()
    for d in (quiet, open_):
        db.session.add(CampSignup(camp_id=camp.id, donor_id=d.id))
    db.session.commit()
    page = _c(app, h, "hospital").get("/hospital/camps").get_data(as_text=True)
    assert quiet.name in page and quiet.phone not in page and open_.phone in page


def test_erasing_a_donor_removes_camp_signups(app):
    h = make_hospital()
    camp = Camp(hospital_id=h.id, title="T" * 6, venue="v", city="Sukkur", starts_at=datetime.utcnow() + timedelta(days=2),
                ends_at=datetime.utcnow() + timedelta(days=2, hours=3), capacity=5)
    d = make_donor("O+")
    db.session.add(camp); db.session.flush(); db.session.add(CampSignup(camp_id=camp.id, donor_id=d.id)); db.session.commit()
    privacy.erase_donor(d)
    assert CampSignup.query.count() == 0


# ------------------------------------------------------------------- analytics
def _fulfil(scene, donor, hours_after=5):
    scene.request.approved_at = datetime.utcnow() - timedelta(hours=hours_after)
    scene.request.units_required = 1
    db.session.commit()
    resp = allocation.pledge(donor, scene.request.id, consent_to_share=True)
    allocation.confirm_donation(scene.hospital, resp.id)
    return resp


def test_fulfilment_time_and_response_stats(app, scene):
    _fulfil(scene, scene.donors[0])
    s = analytics.fulfilment_stats()
    assert s["fulfilled"] == 1 and 4.9 <= s["average_hours"] <= 5.2
    r = analytics.response_stats()
    assert r["offers"] == 1 and r["completed"] == 1 and r["completion_rate"] == 100
    assert analytics.response_stats(make_hospital().id)["offers"] == 0
    assert analytics.fulfilment_stats(scene.hospital.id)["fulfilled"] == 1


def test_demand_and_supply(app, scene):
    rows = {r["group"]: r for r in analytics.demand_supply()}
    assert rows["O+"]["units_needed"] == 3 and rows["O+"]["donors_available"] == 2 and rows["O-"]["donors_available"] == 1
    assert {r["city"] for r in analytics.city_demand_supply()} == {"Sukkur"}


def test_csv_is_safe_against_formula_injection():
    out = analytics.to_csv(["a", "b"], [["=HYPERLINK(\"x\")", "+1"], ["@cmd", "-2"], ["ok", None]])
    lines = out.strip().splitlines()
    assert lines[1].startswith("\"'=HYPERLINK") and "'+1" in lines[1] and "'@cmd" in lines[2] and "'-2" in lines[2]
    assert lines[3] == "ok,"


def test_csv_exports_hold_no_personal_details(app, scene):
    _fulfil(scene, scene.donors[0])
    a = _admin(app)
    body = a.get("/admin/analytics/requests.csv").get_data(as_text=True)
    assert body.splitlines()[0].startswith("request_id,blood_group")
    for secret in (scene.patient.name, scene.patient.email, "Test Patient Name", "Secret ward note", scene.donors[0].name,
                   scene.donors[0].phone, "03110000000"):
        assert secret not in body
    sd = a.get("/admin/analytics/supply-demand.csv").get_data(as_text=True)
    assert "O+" in sd and "city:Sukkur" in sd
    assert _c(app, scene.hospital, "hospital").get("/admin/analytics/requests.csv").status_code == 403
    mine = _c(app, scene.hospital, "hospital").get("/hospital/analytics/requests.csv").get_data(as_text=True)
    assert len(mine.strip().splitlines()) == 2
    other = _c(app, make_hospital(), "hospital").get("/hospital/analytics/requests.csv").get_data(as_text=True)
    assert len(other.strip().splitlines()) == 1


def test_analytics_pages_render(app, scene):
    _fulfil(scene, scene.donors[0])
    assert "Demand and supply" in _admin(app).get("/admin/analytics").get_data(as_text=True)
    assert "Requests fulfilled" in _c(app, scene.hospital, "hospital").get("/hospital/analytics").get_data(as_text=True)


# ---------------------------------------------------------------------- badges
def test_streak_rules():
    d = date
    assert badges.streak([d(2024, 3, 1), d(2025, 2, 1), d(2026, 1, 15)], today=d(2026, 6, 1)) == 3
    assert badges.streak([d(2020, 1, 1), d(2025, 2, 1), d(2026, 1, 15)], today=d(2026, 6, 1)) == 2
    assert badges.streak([d(2023, 1, 1)], today=d(2026, 6, 1)) == 0 and badges.streak([]) == 0


def test_badges_use_confirmed_donations_only(app, scene):
    donor = scene.donors[0]
    s = badges.summary(donor)
    assert s["donations"] == 0 and not any(b["earned"] for b in s["badges"]) and s["can_donate_now"]
    resp = allocation.pledge(donor, scene.request.id, consent_to_share=True)          # an offer is not a donation
    assert badges.summary(donor)["donations"] == 0
    allocation.confirm_donation(scene.hospital, resp.id)
    db.session.refresh(donor)
    s = badges.summary(donor)
    assert s["donations"] == 1 and s["units"] == 1 and s["badges"][0]["earned"] and not s["badges"][1]["earned"]
    assert not s["can_donate_now"] and s["days_left"] > 80


def test_reliable_badge_needs_no_missed_appointments(app, scene):
    donor = scene.donors[0]
    for i in range(3):
        req = make_request(scene.patient, scene.hospital, group="O+", units=1)
        resp = allocation.pledge(donor, req.id, consent_to_share=True)
        allocation.confirm_donation(scene.hospital, resp.id)
        donor.last_donation_date = None; db.session.commit()
    db.session.refresh(donor)
    extra = {b["name"]: b["earned"] for b in badges.summary(donor)["extra"]}
    assert extra["Reliable"] is True
    donor.responses[0].no_show_at = datetime.utcnow(); db.session.commit()
    assert {b["name"]: b["earned"] for b in badges.summary(donor)["extra"]}["Reliable"] is False


def test_dashboard_shows_the_badge_panel(app):
    d = make_donor("O+")
    page = _c(app, d, "donor").get("/donor/dashboard").get_data(as_text=True)
    assert "Your donations" in page and "First donation" in page and "Can you donate right now?" in page

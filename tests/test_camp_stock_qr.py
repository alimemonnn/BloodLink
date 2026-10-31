"""Donation camps: local-time clock, QR check-in for camp places, and blood stock filled by camp donations."""
from datetime import datetime, timedelta

import pytest

from conftest import login, make_donor, make_hospital
from models import BloodStock, Camp, CampSignup, db
from utils import camps, trust


def _c(app, user, role):
    c = app.test_client(); login(c, user, role)
    return c


def _camp(hospital, hours_ahead=1, capacity=3):
    c = Camp(hospital_id=hospital.id, title="Blood Drive", venue="Hall", city=hospital.city,
             starts_at=datetime.utcnow() + timedelta(hours=hours_ahead),
             ends_at=datetime.utcnow() + timedelta(hours=hours_ahead + 4), capacity=capacity)
    db.session.add(c); db.session.commit()
    return c


def _stock(hospital, group):
    row = BloodStock.query.filter_by(hospital_id=hospital.id, blood_group=group).first()
    return row.units if row else 0


# ------------------------------------------------------------------ stock is filled automatically
def test_recorded_camp_donation_adds_units_to_stock(app):
    hospital, donor = make_hospital(), make_donor("B+")
    s = camps.join(_camp(hospital), donor)
    assert _stock(hospital, "B+") == 0
    camps.record(hospital, s.id, "donated", 1)
    assert _stock(hospital, "B+") == 1
    other = make_donor("B+")
    s2 = camps.join(_camp(hospital), other)
    camps.record(hospital, s2.id, "donated", 1)
    assert _stock(hospital, "B+") == 2                          # adds to what is already there
    assert _stock(hospital, "O-") == 0                          # other groups untouched


def test_stock_adds_to_a_number_the_hospital_typed_and_never_twice(app):
    hospital, donor = make_hospital(), make_donor("O-")
    db.session.add(BloodStock(hospital_id=hospital.id, blood_group="O-", units=5)); db.session.commit()
    s = camps.join(_camp(hospital), donor)
    camps.record(hospital, s.id, "donated", 1)
    with pytest.raises(camps.CampError):
        camps.record(hospital, s.id, "donated", 1)              # already recorded
    assert _stock(hospital, "O-") == 6


def test_arrived_or_no_show_does_not_change_stock(app):
    hospital = make_hospital()
    a, b = make_donor("A+"), make_donor("A+")
    camp = _camp(hospital)
    sa, sb = camps.join(camp, a), camps.join(camp, b)
    camps.record(hospital, sa.id, "attended")
    camps.record(hospital, sb.id, "no_show")
    assert _stock(hospital, "A+") == 0


def test_public_stock_page_shows_camp_blood(app, client):
    hospital, donor = make_hospital(), make_donor("AB-")
    s = camps.join(_camp(hospital), donor)
    _c(app, hospital, "hospital").post(f"/hospital/camps/signups/{s.id}/record", data={"action": "donated", "units": "1"})
    page = client.get("/stock").get_data(as_text=True)
    assert hospital.hospital_name in page and "AB-" in page


def test_roster_page_says_stock_is_automatic(app):
    hospital = make_hospital()
    camp = _camp(hospital)
    page = _c(app, hospital, "hospital").get(f"/hospital/camps/{camp.id}/roster").get_data(as_text=True)
    assert "added to your blood stock automatically" in page


# ------------------------------------------------------------------ QR check-in for camp places
def test_camp_code_round_trip_and_tampering(app):
    hospital, donor = make_hospital(), make_donor("O+")
    s = camps.join(_camp(hospital), donor)
    code = trust.camp_checkin_code(s)
    assert code.startswith(f"C{s.id}-")
    assert trust.resolve_camp_checkin(code) is s and trust.resolve_camp_checkin(code.lower()) is s
    for bad in ("", "C1-000000", f"C{s.id}-FFFFFF", "C999999-ABCDEF", f"{s.id}-{code[-6:]}"):
        assert trust.resolve_camp_checkin(bad) is None


def test_donor_sees_the_camp_qr_and_others_cannot(app):
    hospital = make_hospital()
    mine, other = make_donor("O+"), make_donor("O+")
    s = camps.join(_camp(hospital), mine)
    page = _c(app, mine, "donor").get(f"/donor/camp-checkin/{s.id}")
    text = page.get_data(as_text=True)
    assert page.status_code == 200 and trust.camp_checkin_code(s) in text and "data:image/svg+xml" in text
    assert _c(app, other, "donor").get(f"/donor/camp-checkin/{s.id}").status_code == 404
    detail = _c(app, mine, "donor").get(f"/camps/{s.camp_id}").get_data(as_text=True)
    assert "Check-in QR" in detail


def test_waitlisted_or_cancelled_places_get_no_qr(app):
    hospital = make_hospital()
    camp = _camp(hospital, capacity=1)
    first, second = make_donor("O+"), make_donor("O+")
    camps.join(camp, first)
    waiting = camps.join(camp, second)
    assert _c(app, second, "donor").get(f"/donor/camp-checkin/{waiting.id}").status_code == 302


def test_hospital_scans_the_camp_code_and_marks_arrival(app):
    hospital, donor = make_hospital(), make_donor("O+")
    s = camps.join(_camp(hospital), donor)
    h = _c(app, hospital, "hospital")
    code = trust.camp_checkin_code(s)
    for value in (code, f"http://localhost/hospital/checkin?code={code}"):
        page = h.post("/hospital/checkin", data={"code": value}).get_data(as_text=True)
        assert donor.name in page and "Confirm arrival at the camp" in page
    h.post(f"/hospital/camp-checkin/{s.id}/arrived")
    db.session.expire_all()
    assert db.session.get(CampSignup, s.id).status == "Attended"
    assert "Already checked in" in h.post("/hospital/checkin", data={"code": code}).get_data(as_text=True)
    assert _stock(hospital, "O+") == 0                           # arrival is not a donation


def test_another_hospital_cannot_use_the_code(app):
    hospital, donor = make_hospital(), make_donor("O+")
    s = camps.join(_camp(hospital), donor)
    intruder = _c(app, make_hospital(), "hospital")
    page = intruder.post("/hospital/checkin", data={"code": trust.camp_checkin_code(s)}).get_data(as_text=True)
    assert donor.name not in page
    assert intruder.post(f"/hospital/camp-checkin/{s.id}/arrived").status_code == 404
    db.session.expire_all()
    assert db.session.get(CampSignup, s.id).status == "Signed up"


def test_donor_cannot_open_the_hospital_scan_pages(app):
    donor = make_donor("O+")
    c = _c(app, donor, "donor")
    assert c.get("/hospital/checkin").status_code == 403
    assert c.post("/hospital/camp-checkin/1/arrived").status_code == 403


# ------------------------------------------------------------------ local clock
def test_camp_roster_window_uses_the_local_clock(app):
    """With a +5 h local clock, a camp starting in 6 local hours is NOT open yet, one in 1 hour is."""
    app.config["LOCAL_UTC_OFFSET_MINUTES"] = 300
    hospital = make_hospital()
    soon = Camp(hospital_id=hospital.id, title="Soon camp", venue="Hall", city="Sukkur",
                starts_at=camps.local_now() + timedelta(hours=1), ends_at=camps.local_now() + timedelta(hours=5), capacity=3)
    later = Camp(hospital_id=hospital.id, title="Later camp", venue="Hall", city="Sukkur",
                 starts_at=camps.local_now() + timedelta(hours=6), ends_at=camps.local_now() + timedelta(hours=9), capacity=3)
    db.session.add_all([soon, later]); db.session.commit()
    a, b = camps.join(soon, make_donor("O+")), camps.join(later, make_donor("O+"))
    camps.record(hospital, a.id, "donated", 1)
    with pytest.raises(camps.CampError):
        camps.record(hospital, b.id, "donated", 1)


def test_new_camp_must_start_after_local_now(app):
    app.config["LOCAL_UTC_OFFSET_MINUTES"] = 300
    past_local = (camps.local_now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    ok_local = (camps.local_now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    end = (camps.local_now() + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M")
    base = {"title": "Evening drive", "venue": "Hall", "city": "Sukkur", "ends_at": end, "capacity": "10"}
    _, errors = camps.validate({**base, "starts_at": past_local})
    assert errors
    _, errors = camps.validate({**base, "starts_at": ok_local})
    assert not errors

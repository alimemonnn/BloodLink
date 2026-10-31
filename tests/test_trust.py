"""QR check-in, no-shows, certificates and public verification."""
from datetime import datetime, timedelta

import pytest

from conftest import login, make_donor, make_hospital, make_patient, make_request
from models import DonationResponse, db
from utils import allocation, chat, privacy, ratelimit, trust
from models import ChatMessage


@pytest.fixture
def booked(app, scene):
    resp = allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)
    allocation.schedule_appointment(scene.hospital, resp.id, datetime.utcnow() + timedelta(days=1))
    db.session.refresh(resp)
    return resp


def _c(app, user, role):
    c = app.test_client(); login(c, user, role)
    return c


# --------------------------------------------------------------------- codes
def test_checkin_code_round_trip_and_tampering(app, booked):
    code = trust.checkin_code(booked)
    assert trust.resolve_checkin(code) is booked
    assert trust.resolve_checkin(code.lower()) is booked and trust.resolve_checkin(f" BL-{code} ") is booked
    for bad in ("", "abc", f"{booked.id}-000000", f"{booked.id + 1}-{code.split('-')[1]}", "1-2-3", None):
        assert trust.resolve_checkin(bad) is None


def test_checkin_code_is_tied_to_the_appointment_time(app, scene, booked):
    old = trust.checkin_code(booked)
    allocation.schedule_appointment(scene.hospital, booked.id, datetime.utcnow() + timedelta(days=2))
    db.session.refresh(booked)
    assert trust.resolve_checkin(old) is None                 # an old screenshot stops working
    assert trust.resolve_checkin(trust.checkin_code(booked)) is booked


# ------------------------------------------------------------- donor shows QR
def test_donor_sees_qr_only_for_own_booked_offer(app, scene, booked):
    page = _c(app, scene.donors[0], "donor").get(f"/donor/checkin/{booked.id}")
    text = page.get_data(as_text=True)
    assert page.status_code == 200 and trust.checkin_code(booked) in text and "data:image/svg+xml" in text
    assert _c(app, scene.donors[1], "donor").get(f"/donor/checkin/{booked.id}").status_code == 404
    assert _c(app, scene.patient, "patient").get(f"/donor/checkin/{booked.id}").status_code == 403
    other = allocation.pledge(scene.donors[1], scene.request.id, consent_to_share=True)     # no appointment yet
    assert _c(app, scene.donors[1], "donor").get(f"/donor/checkin/{other.id}").status_code == 302


# ------------------------------------------------------------ hospital scans
def test_hospital_finds_the_donor_from_a_code_or_scanned_url(app, scene, booked):
    h = _c(app, scene.hospital, "hospital")
    code = trust.checkin_code(booked)
    for value in (code, f"http://localhost/hospital/checkin?code={code}"):
        page = h.post("/hospital/checkin", data={"code": value}).get_data(as_text=True)
        assert scene.donors[0].name in page and "Confirm arrival" in page
    assert scene.donors[0].name not in h.get("/hospital/checkin").get_data(as_text=True)


def test_other_hospitals_and_other_roles_cannot_use_the_code(app, scene, booked):
    page = _c(app, make_hospital(), "hospital").post("/hospital/checkin", data={"code": trust.checkin_code(booked)})
    assert scene.donors[0].name not in page.get_data(as_text=True) and "not valid for this hospital" in page.get_data(as_text=True)
    assert _c(app, scene.donors[0], "donor").get("/hospital/checkin").status_code == 403
    assert app.test_client().get("/hospital/checkin").status_code == 302


def test_guessing_codes_is_rate_limited(app, scene, booked):
    ratelimit.clear_all()
    h = _c(app, scene.hospital, "hospital")
    codes = [h.post("/hospital/checkin", data={"code": f"{booked.id}-{i:06X}"}).status_code for i in range(35)]
    assert codes[-1] == 429


def test_confirming_arrival_records_it_without_counting_blood(app, scene, booked):
    h = _c(app, scene.hospital, "hospital")
    assert h.post(f"/hospital/checkin/{booked.id}/arrived").status_code == 302
    db.session.expire_all()
    assert booked.checked_in_at is not None
    assert scene.request.units_confirmed == 0 and booked.response_status == "Appointment Scheduled"
    assert any("checked in" in m.body for m in ChatMessage.query.filter_by(kind="event"))
    stamp = booked.checked_in_at
    h.post(f"/hospital/checkin/{booked.id}/arrived")
    db.session.expire_all()
    assert booked.checked_in_at == stamp                                    # second scan changes nothing
    assert _c(app, make_hospital(), "hospital").post(f"/hospital/checkin/{booked.id}/arrived").status_code == 404


def test_cancelled_offers_cannot_be_checked_in(app, scene, booked):
    allocation.cancel_response(booked.id, "donor", scene.donors[0].id)
    _c(app, scene.hospital, "hospital").post(f"/hospital/checkin/{booked.id}/arrived")
    db.session.expire_all()
    assert booked.checked_in_at is None


# ------------------------------------------------------------------ no-shows
def test_no_show_closes_the_offer_and_counts_against_matching(app, scene, booked):
    r = _c(app, scene.hospital, "hospital").post(f"/hospital/responses/{booked.id}/no-show")
    assert r.status_code == 302
    db.session.expire_all()
    assert booked.no_show_at is not None and booked.response_status == "Cancelled"
    assert scene.request.status == "Approved" and scene.request.units_confirmed == 0   # still open for others
    from utils.matching import rank_donors
    m = {x.donor.id: x for x in rank_donors(make_request(scene.patient, scene.hospital, group="O+"))}
    assert any("missed appointment" in reason for reason in m[scene.donors[0].id].reasons)


def test_no_show_is_refused_after_arrival_and_for_other_hospitals(app, scene, booked):
    h = _c(app, scene.hospital, "hospital")
    assert _c(app, make_hospital(), "hospital").post(f"/hospital/responses/{booked.id}/no-show").status_code == 404
    h.post(f"/hospital/checkin/{booked.id}/arrived")
    h.post(f"/hospital/responses/{booked.id}/no-show")
    db.session.expire_all()
    assert booked.no_show_at is None and booked.response_status == "Appointment Scheduled"


# --------------------------------------------------------------- certificates
@pytest.fixture
def done(app, scene, booked):
    allocation.confirm_donation(scene.hospital, booked.id)
    db.session.refresh(booked)
    return booked


def test_certificate_pdf_for_the_donor_only(app, scene, done):
    r = _c(app, scene.donors[0], "donor").get(f"/donor/certificate/{done.id}.pdf")
    assert r.status_code == 200 and r.mimetype == "application/pdf" and r.data.startswith(b"%PDF")
    assert len(r.data) > 1500 and "attachment" in r.headers["Content-Disposition"]
    assert _c(app, scene.donors[1], "donor").get(f"/donor/certificate/{done.id}.pdf").status_code == 404
    assert app.test_client().get(f"/donor/certificate/{done.id}.pdf").status_code == 302


def test_no_certificate_until_the_hospital_confirms(app, scene, booked):
    assert _c(app, scene.donors[0], "donor").get(f"/donor/certificate/{booked.id}.pdf").status_code == 404


def test_verification_page_confirms_genuine_codes_and_shows_little(app, scene, done):
    code = trust.certificate_code(done)
    c = app.test_client()
    page = c.get(f"/verify/{code}").get_data(as_text=True)
    first, last = scene.donors[0].name.split()[0], scene.donors[0].name.split()[-1]
    assert "Genuine" in page and f"{first} {last[0]}." in page
    assert scene.donors[0].email not in page and scene.donors[0].phone not in page and scene.donors[0].name not in page
    assert scene.hospital.hospital_name in page
    assert "Genuine" in c.post("/verify", data={"code": code.lower()}).get_data(as_text=True)


def test_verification_rejects_forged_and_changed_certificates(app, scene, done):
    code = trust.certificate_code(done)
    c = app.test_client()
    for bad in ("BL-00001-DEADBEEF", "nonsense", f"BL-{done.id:05d}-{code[-8:][::-1]}", f"BL-{done.id + 7:05d}-{code[-8:]}"):
        assert "not valid" in c.get(f"/verify/{bad}").get_data(as_text=True)
    done.units_collected = 9                                                   # tampering with the record
    db.session.commit()
    assert "not valid" in c.get(f"/verify/{code}").get_data(as_text=True)


def test_certificate_is_not_valid_for_an_unconfirmed_offer(app, scene, booked):
    assert trust.resolve_certificate(f"BL-{booked.id:05d}-{'A' * 8}") is None


def test_verification_is_rate_limited(app, done):
    ratelimit.clear_all()
    c = app.test_client()
    codes = [c.get(f"/verify/BL-00001-{i:08X}").status_code for i in range(35)]
    assert codes[-1] == 429


def test_erased_donor_shows_as_name_withdrawn(app, scene, done):
    code = trust.certificate_code(done)
    privacy.erase_donor(scene.donors[0])
    page = app.test_client().get(f"/verify/{code}").get_data(as_text=True)
    assert "Name withdrawn" in page


def test_public_name_helper():
    class D:  # noqa
        def __init__(self, n): self.name = n
    assert trust.public_name(D("Bilal Ahmed")) == "Bilal A."
    assert trust.public_name(D("Madonna")) == "Madonna"
    assert trust.public_name(D("Deleted donor")) == "Name withdrawn"


def test_history_page_offers_qr_and_certificate_links(app, scene, booked):
    page = _c(app, scene.donors[0], "donor").get("/donor/history").get_data(as_text=True)
    assert f"/donor/checkin/{booked.id}" in page
    allocation.confirm_donation(scene.hospital, booked.id)
    page = _c(app, scene.donors[0], "donor").get("/donor/history").get_data(as_text=True)
    assert f"/donor/certificate/{booked.id}.pdf" in page

"""End-to-end through the real routes, plus a render-every-page smoke test."""
import re

import pytest

from conftest import PASSWORD, make_donor, make_hospital, make_patient, make_request, login
from models import Admin, BloodRequest, DonationResponse, db
from utils import allocation


def test_three_donors_one_request_through_the_web_interface(app, client):
    """Patient posts 3 units -> hospital approves -> 3 donors offer -> hospital confirms each."""
    hospital, patient = make_hospital(), make_patient()
    donors = [make_donor("O+", share=True), make_donor("O-"), make_donor("O+")]

    # patient creates the request
    pc = app.test_client(); login(pc, patient, "patient")
    r = pc.post("/patient/requests/new", data={
        "patient_name": "Fictional Person", "blood_group_required": "O+", "units_required": "3",
        "urgency": "Urgent", "hospital_id": str(hospital.id), "location": "Sukkur",
        "contact_number": "03111234567", "description": "ward 3"}, follow_redirects=True)
    req = BloodRequest.query.one()
    assert req.status == "Pending Hospital Approval" and req.units_required == 3
    # a double click does not create a duplicate
    pc.post("/patient/requests/new", data={
        "patient_name": "Fictional Person", "blood_group_required": "O+", "units_required": "3",
        "urgency": "Urgent", "hospital_id": str(hospital.id), "location": "Sukkur",
        "contact_number": "03111234567"})
    assert BloodRequest.query.count() == 1

    # donors cannot see or answer it until the hospital approves
    dc = [app.test_client() for _ in donors]
    for c, d in zip(dc, donors):
        login(c, d, "donor")
    assert b"Fictional" not in dc[0].get("/donor/requests").data
    dc[0].post(f"/donor/requests/{req.id}/respond", data={"share_with_hospital": "on"})
    assert DonationResponse.query.count() == 0

    hc = app.test_client(); login(hc, hospital, "hospital")
    hc.post(f"/hospital/requests/{req.id}/approve", data={"hospital_notes": "verified"})
    db.session.expire_all()
    assert db.session.get(BloodRequest, req.id).status == "Approved"

    # consent tick is mandatory
    dc[0].post(f"/donor/requests/{req.id}/respond", data={})
    assert DonationResponse.query.count() == 0
    for c in dc:
        c.post(f"/donor/requests/{req.id}/respond", data={"share_with_hospital": "on"})
    assert DonationResponse.query.count() == 3

    page = hc.get(f"/hospital/requests/{req.id}").data.decode()
    assert "Pledged (not yet verified)" in page and "0</dd>" in page

    # hospital confirms one at a time
    ids = [r.id for r in DonationResponse.query.order_by(DonationResponse.id)]
    expected = [("Partially Fulfilled", 1, 2), ("Partially Fulfilled", 2, 1), ("Fulfilled", 3, 0)]
    for resp_id, (status, confirmed, remaining) in zip(ids, expected):
        hc.post(f"/hospital/requests/{req.id}/responses/{resp_id}/confirm", data={"units": "1"})
        db.session.expire_all()
        r = db.session.get(BloodRequest, req.id)
        assert (r.status, r.units_confirmed, r.units_remaining) == (status, confirmed, remaining)

    # the patient sees the result but has no way to confirm anything
    detail = pc.get(f"/patient/requests/{req.id}").data.decode()
    assert "Fulfilled" in detail and "3 of 3 units confirmed" in detail
    assert "/confirm" not in detail
    # a repeated POST of the final confirmation changes nothing
    hc.post(f"/hospital/requests/{req.id}/responses/{ids[-1]}/confirm", data={"units": "1"})
    db.session.expire_all()
    assert db.session.get(BloodRequest, req.id).units_confirmed == 3
    assert allocation.check_consistency() == []


def test_hospital_schedule_ineligible_and_close_flow(app, client):
    hospital, patient = make_hospital(), make_patient()
    req = make_request(patient, hospital, group="O+", units=2)
    d1, d2 = make_donor("O+"), make_donor("O+")
    r1 = allocation.pledge(d1, req.id, 1, True); r2 = allocation.pledge(d2, req.id, 1, True)
    hc = app.test_client(); login(hc, hospital, "hospital")
    base = f"/hospital/requests/{req.id}/responses"
    hc.post(f"{base}/{r1.id}/contact")
    hc.post(f"{base}/{r1.id}/schedule", data={"appointment_at": "2099-01-01T10:00", "note": "bring ID"})
    hc.post(f"{base}/{r2.id}/ineligible", data={"note": "screening", "deferral_days": "30"})
    db.session.expire_all()
    assert db.session.get(DonationResponse, r1.id).response_status == "Appointment Scheduled"
    assert db.session.get(DonationResponse, r2.id).response_status == "Ineligible"
    assert db.session.get(type(d2), d2.id).deferred_until is not None
    # closing needs a reason
    hc.post(f"/hospital/requests/{req.id}/close", data={"reason": ""})
    assert db.session.get(BloodRequest, req.id).status == "Approved"
    hc.post(f"/hospital/requests/{req.id}/close", data={"reason": "Blood arranged elsewhere"})
    db.session.expire_all()
    assert db.session.get(BloodRequest, req.id).status == "Cancelled"


def test_patient_cancel_keeps_history(app, client):
    hospital, patient = make_hospital(), make_patient()
    req = make_request(patient, hospital)
    pc = app.test_client(); login(pc, patient, "patient")
    pc.post(f"/patient/requests/{req.id}/cancel", data={"reason": "found donor"})
    db.session.expire_all()
    r = db.session.get(BloodRequest, req.id)
    assert r is not None and r.status == "Cancelled" and r.closed_reason == "found donor"
    assert b"Cancelled" in pc.get("/patient/requests").data


def test_donor_cancels_own_offer_through_the_ui(app, client):
    hospital, patient = make_hospital(), make_patient()
    req = make_request(patient, hospital)
    d = make_donor("O+")
    resp = allocation.pledge(d, req.id, 1, True)
    dc = app.test_client(); login(dc, d, "donor")
    dc.post(f"/donor/history/{resp.id}/cancel")
    db.session.expire_all()
    assert db.session.get(DonationResponse, resp.id).response_status == "Cancelled"


def test_invalid_unit_counts_are_rejected_server_side(app):
    hospital, patient = make_hospital(), make_patient()
    pc = app.test_client(); login(pc, patient, "patient")
    for units in ("0", "-3", "abc", "999"):
        pc.post("/patient/requests/new", data={
            "patient_name": "X Y", "blood_group_required": "O+", "units_required": units, "urgency": "Normal",
            "hospital_id": str(hospital.id), "location": "Sukkur", "contact_number": "03111234567"})
    assert BloodRequest.query.count() == 0


def test_admin_cannot_force_a_request_to_fulfilled(app):
    hospital, patient = make_hospital(), make_patient()
    req = make_request(patient, hospital, units=3)
    admin = Admin(name="A", email="admin@example.com"); admin.set_password(PASSWORD)
    db.session.add(admin); db.session.commit()
    ac = app.test_client(); login(ac, admin, "admin")
    ac.post(f"/admin/requests/{req.id}/status", data={"status": "Fulfilled"})
    db.session.expire_all()
    assert db.session.get(BloodRequest, req.id).status == "Approved"


@pytest.fixture
def world(app):
    hospital, patient = make_hospital(), make_patient()
    req = make_request(patient, hospital, group="O+", units=3)
    donors = [make_donor("O+", share=True), make_donor("O-")]
    resp = allocation.pledge(donors[0], req.id, 1, True)
    allocation.confirm_donation(hospital, resp.id)
    allocation.pledge(donors[1], req.id, 1, True)
    admin = Admin(name="A", email="admin2@example.com"); admin.set_password(PASSWORD)
    db.session.add(admin); db.session.commit()
    from models import ContactMessage, DataRequest
    db.session.add_all([ContactMessage(name="V", message="hi"), DataRequest(kind="delete", email="x@example.com")])
    db.session.commit()
    return dict(hospital=hospital, patient=patient, req=req, donors=donors, admin=admin)


def test_every_page_renders_for_every_role(app, world):
    w = world
    plans = {
        ("admin", w["admin"]): ["/admin/dashboard", "/admin/analytics", "/admin/donors", "/admin/patients",
                                "/admin/hospitals", "/admin/hospitals/new", "/admin/requests", "/admin/users",
                                "/admin/privacy", f"/admin/requests/{w['req'].id}", f"/admin/donors/{w['donors'][0].id}",
                                f"/admin/patients/{w['patient'].id}", f"/admin/hospitals/{w['hospital'].id}"],
        ("donor", w["donors"][0]): ["/donor/dashboard", "/donor/requests", "/donor/history", "/donor/notifications",
                                    "/donor/profile", "/account/delete"],
        ("patient", w["patient"]): ["/patient/dashboard", "/patient/requests", "/patient/requests/new",
                                    f"/patient/requests/{w['req'].id}", "/patient/profile", "/account/delete",
                                    "/find-blood?blood_group=O%2B"],
        ("hospital", w["hospital"]): ["/hospital/dashboard", "/hospital/requests", f"/hospital/requests/{w['req'].id}",
                                      "/hospital/profile"],
    }
    for (role, user), urls in plans.items():
        c = app.test_client(); login(c, user, role)
        for url in urls:
            r = c.get(url)
            assert r.status_code == 200, f"{role} {url} -> {r.status_code}"
            assert b"Traceback" not in r.data and b"UndefinedError" not in r.data


def test_pending_request_edit_page_renders(app):
    hospital, patient = make_hospital(), make_patient()
    req = make_request(patient, hospital, status="Pending Hospital Approval")
    pc = app.test_client(); login(pc, patient, "patient")
    assert pc.get(f"/patient/requests/{req.id}/edit").status_code == 200

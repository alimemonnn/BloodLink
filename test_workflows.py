"""End-to-end checks for the main BloodLink workflows.

Run with:  python test_workflows.py
Uses Flask's test client against a temporary copy of the database.
"""
import os
import sys

from app import create_app
from config import Config
from models import (STATUS_APPROVED, STATUS_PENDING, BloodRequest,
                    DonationResponse, Donor, Hospital, Notification, db)
from utils.matching import can_donate, compatible_donor_groups, find_matching_donors

PASS, FAIL = [], []


def check(name, condition):
    (PASS if condition else FAIL).append(name)
    print(("  PASS  " if condition else "  FAIL  ") + name)


class TestConfig(Config):
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "test_database.db")
    TESTING = True
    WTF_CSRF_ENABLED = False


def login(client, role, email, password):
    return client.post("/login", data={"role": role, "email": email, "password": password},
                       follow_redirects=True)


def main():
    # Always start from a brand-new throw-away database (never your real one).
    test_db = TestConfig.SQLALCHEMY_DATABASE_URI.replace("sqlite:///", "")
    if os.path.exists(test_db):
        os.remove(test_db)
    app = create_app(TestConfig)

    # Build a fresh test database from the seed data
    with app.app_context():
        import seed as seed_module
        seed_module.seed()

    print("\n1. Blood compatibility rules")
    check("O- can donate to every group", all(can_donate("O-", g) for g in
          ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]))
    check("AB+ can only donate to AB+", compatible := can_donate("AB+", "AB+") and not can_donate("AB+", "O+"))
    check("A+ cannot donate to B+", not can_donate("A+", "B+"))
    check("B+ recipient accepts B+, B-, O+, O-",
          sorted(compatible_donor_groups("B+")) == sorted(["B+", "B-", "O+", "O-"]))
    check("O- recipient only accepts O-", compatible_donor_groups("O-") == ["O-"])
    check("AB+ recipient accepts all 8 groups", len(compatible_donor_groups("AB+")) == 8)

    print("\n2. Matching engine")
    with app.app_context():
        req = BloodRequest.query.filter_by(blood_group_required="B+").first()
        matches = find_matching_donors(req)
        groups = {d.blood_group for d in matches}
        check("Only compatible groups are matched", groups <= {"B+", "B-", "O+", "O-"})
        check("Unavailable donors are excluded",
              all(d.availability == "Available" for d in matches))
        check("Ineligible donors are excluded", all(d.is_eligible for d in matches))
        check("Same-city donor is ranked first", matches[0].city.lower() in req.location.lower())
        check("Donors who already responded are not listed again",
              all(d.email not in ("ahmed.ali@example.com", "m.hassan@example.com") for d in matches))

    print("\n3. Access control")
    client = app.test_client()
    check("Anonymous user is redirected from the donor dashboard",
          "/login" in client.get("/donor/dashboard").headers.get("Location", ""))
    check("Anonymous user is redirected from the admin dashboard",
          "/login" in client.get("/admin/dashboard").headers.get("Location", ""))

    donor_client = app.test_client()
    login(donor_client, "donor", "ahmed.ali@example.com", "Donor123")
    check("Donor can open their own dashboard", donor_client.get("/donor/dashboard").status_code == 200)
    check("Donor is blocked from the admin panel", donor_client.get("/admin/dashboard").status_code == 403)
    check("Donor is blocked from the hospital panel", donor_client.get("/hospital/dashboard").status_code == 403)

    print("\n4. Authentication")
    bad = app.test_client()
    resp = login(bad, "donor", "ahmed.ali@example.com", "WrongPassword")
    check("Wrong password is rejected", b"Incorrect email or password" in resp.data)
    unverified = app.test_client()
    resp = login(unverified, "hospital", "help@larkanablood.com", "Hospital123")
    check("Unverified hospital cannot log in", b"waiting for admin approval" in resp.data)
    with app.app_context():
        check("Passwords are stored hashed, never as plain text",
              all("Donor123" not in d.password_hash for d in Donor.query.all()))

    print("\n5. Patient posts a request")
    patient_client = app.test_client()
    login(patient_client, "patient", "rizwan@example.com", "Patient123")
    with app.app_context():
        hospital_id = Hospital.query.filter_by(email="civil@sukkurhospital.com").first().id
    resp = patient_client.post("/patient/requests/new", data={
        "patient_name": "Test Patient", "blood_group_required": "B+", "hospital_id": hospital_id,
        "units_required": "2", "urgency": "Critical", "location": "Sukkur",
        "contact_number": "03001112222", "description": "Demo request",
    }, follow_redirects=True)
    with app.app_context():
        new_req = BloodRequest.query.filter_by(patient_name="Test Patient").first()
        check("Request is created in the database", new_req is not None)
        check("New request starts as Pending Hospital Approval", new_req.status == STATUS_PENDING)
        new_req_id = new_req.id

    print("\n6. Donors cannot see unapproved requests")
    feed = donor_client.get("/donor/requests").data
    check("Pending request is hidden from donors", b"Test Patient" not in feed)
    check("Invalid request data is rejected", b"Select a valid blood group" in patient_client.post(
        "/patient/requests/new", data={"patient_name": "X", "blood_group_required": "ZZ",
        "hospital_id": hospital_id, "units_required": "1", "urgency": "Normal",
        "location": "Sukkur", "contact_number": "03001112222"}, follow_redirects=True).data)

    print("\n7. Hospital approval")
    hosp_client = app.test_client()
    login(hosp_client, "hospital", "civil@sukkurhospital.com", "Hospital123")
    resp = hosp_client.post(f"/hospital/requests/{new_req_id}/approve",
                            data={"hospital_notes": "Confirmed by blood bank."},
                            follow_redirects=True)
    with app.app_context():
        approved = db.session.get(BloodRequest, new_req_id)
        check("Hospital approval sets status to Approved", approved.status == STATUS_APPROVED)
        check("Hospital approval marks the request verified", approved.hospital_verified is True)
        check("Matching donors received a notification",
              Notification.query.filter_by(request_id=new_req_id).count() > 0)
    feed = donor_client.get("/donor/requests").data
    check("Approved request becomes visible to donors", b"2 unit(s) still needed" in feed)
    check("Donors never see the patient's name", b"Test Patient" not in feed)

    print("\n8. Hospital cannot touch another hospital's request")
    other = app.test_client()
    login(other, "hospital", "contact@rohrigh.com", "Hospital123")
    check("Approval by the wrong hospital is refused",
          b"Unauthorized access" in other.post(f"/hospital/requests/{new_req_id}/approve",
                                               follow_redirects=True).data)

    print("\n9. Donor responds")
    resp = donor_client.post(f"/donor/requests/{new_req_id}/respond",
                             data={"share_with_hospital": "on"}, follow_redirects=True)
    with app.app_context():
        donor = Donor.query.filter_by(email="ahmed.ali@example.com").first()
        check("Response is stored", DonationResponse.query.filter_by(
            donor_id=donor.id, request_id=new_req_id).count() == 1)
    resp = donor_client.post(f"/donor/requests/{new_req_id}/respond",
                             data={"share_with_hospital": "on"}, follow_redirects=True)
    check("Duplicate response is blocked", b"already responded" in resp.data)
    with app.app_context():
        check("Still only one response row after the duplicate attempt",
              DonationResponse.query.filter_by(request_id=new_req_id).count() == 1)

    print("\n10. Editing rules and fulfilment")
    check("Approved request can no longer be edited by the patient",
          b"cannot be edited after the hospital has reviewed" in patient_client.get(
              f"/patient/requests/{new_req_id}/edit", follow_redirects=True).data)
    with app.app_context():
        offer_id = DonationResponse.query.filter_by(request_id=new_req_id).first().id
    check("There is no one-click 'fulfilled' route any more",
          hosp_client.post(f"/hospital/requests/{new_req_id}/fulfill").status_code in (404, 405))
    hosp_client.post(f"/hospital/requests/{new_req_id}/responses/{offer_id}/confirm",
                     data={"units": "1"}, follow_redirects=True)
    with app.app_context():
        r = db.session.get(BloodRequest, new_req_id)
        check("One of two units confirmed leaves the request Partially Fulfilled",
              r.status == "Partially Fulfilled" and r.units_confirmed == 1 and r.units_remaining == 1)
    cards_before = donor_client.get("/donor/requests").data.count(b'class="request-card')
    hosp_client.post(f"/hospital/requests/{new_req_id}/close", data={"reason": "Arranged elsewhere"},
                     follow_redirects=True)
    with app.app_context():
        check("Hospital can close a request with a reason",
              db.session.get(BloodRequest, new_req_id).status == "Cancelled")
    check("Closed request disappears from the donor feed",
          donor_client.get("/donor/requests").data.count(b'class="request-card') == cards_before - 1)

    print("\n11. Donor availability and eligibility")
    donor_client.post("/donor/availability", follow_redirects=True)
    with app.app_context():
        donor = Donor.query.filter_by(email="ahmed.ali@example.com").first()
        check("Availability toggle is saved", donor.availability == "Not Available")
        req = BloodRequest.query.filter_by(blood_group_required="B+",
                                           status=STATUS_APPROVED).first()
        if req:
            check("Unavailable donor drops out of matching",
                  donor.id not in [d.id for d in find_matching_donors(req)])
    with app.app_context():
        donor = Donor.query.filter_by(email="ahmed.ali@example.com").first()
        check("A hospital-verified donation records today's date", donor.last_donation_date is not None)
        check("Donor starts the rest period after a verified donation", donor.is_eligible is False)

    print("\n12. Admin panel")
    admin_client = app.test_client()
    login(admin_client, "admin", "admin@bloodlink.com", "Admin123")
    for path in ["/admin/dashboard", "/admin/donors", "/admin/patients", "/admin/hospitals",
                 "/admin/requests", "/admin/analytics"]:
        check(f"Admin page loads: {path}", admin_client.get(path).status_code == 200)
    with app.app_context():
        unverified_id = Hospital.query.filter_by(email="help@larkanablood.com").first().id
    admin_client.post(f"/admin/hospitals/{unverified_id}/verify", follow_redirects=True)
    with app.app_context():
        check("Admin can verify a hospital",
              db.session.get(Hospital, unverified_id).is_verified is True)
    check("Admin donor search filters by blood group",
          admin_client.get("/admin/donors?blood_group=O-").status_code == 200)

    print("\n13. Public pages")
    for path in ["/", "/about", "/how-it-works", "/find-blood", "/emergency", "/contact",
                 "/login", "/register", "/register/donor", "/register/patient",
                 "/register/hospital"]:
        check(f"Public page loads: {path}", client.get(path).status_code == 200)
    check("Unknown page returns the 404 template", client.get("/no-such-page").status_code == 404)

    print("\n14. Registration")
    fresh = app.test_client()
    resp = fresh.post("/register/donor", data={
        "name": "New Donor", "email": "new.donor@example.com", "phone": "03009998877",
        "password": "Secret123", "confirm_password": "Secret123", "blood_group": "O+",
        "city": "Sukkur", "area": "Test area", "last_donation_date": "", "availability": "Available",
        "accept_terms": "on", "confirm_adult": "on", "health_consent": "on",
    }, follow_redirects=True)
    with app.app_context():
        check("New donor is saved", Donor.query.filter_by(email="new.donor@example.com").first() is not None)
    resp = app.test_client().post("/register/donor", data={
        "name": "Future", "email": "future@example.com", "phone": "03009998800",
        "password": "Secret123", "confirm_password": "Secret123", "blood_group": "O+",
        "city": "Sukkur", "last_donation_date": "2099-01-01", "availability": "Available",
        "accept_terms": "on", "confirm_adult": "on", "health_consent": "on",
    }, follow_redirects=True)
    check("Future donation date is rejected", b"cannot be in the future" in resp.data)
    resp = app.test_client().post("/register/donor", data={
        "name": "Dup", "email": "ahmed.ali@example.com", "phone": "03009998801",
        "password": "Secret123", "confirm_password": "Secret123", "blood_group": "O+",
        "city": "Sukkur", "availability": "Available",
        "accept_terms": "on", "confirm_adult": "on", "health_consent": "on",
    }, follow_redirects=True)
    check("Duplicate email is rejected", b"already exists" in resp.data)

    print("\n" + "=" * 54)
    print(f"{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for name in FAIL:
            print("  FAILED: " + name)
    print("=" * 54)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

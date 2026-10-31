"""CNIC verification, the Verified donor badge, the admin review and the hospital's nearby-donor page."""
import io

from conftest import PASSWORD, login, make_donor, make_hospital, make_patient, make_request
from models import (CNIC_APPROVED, CNIC_PENDING, CNIC_REJECTED, Admin, DonationResponse, Donor,
                    DonorCNIC, db)
from models.cnic import CNIC_INCOMPLETE
from utils import cnic as cnic_utils
from utils import privacy

JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-body" * 20
NUMBER = "42101-1234567-1"


def _form(email="new.donor@example.com", **extra):
    data = {"name": "New Donor", "email": email, "phone": "03001234567", "blood_group": "O+",
            "city": "Sukkur", "availability": "Available", "password": PASSWORD,
            "confirm_password": PASSWORD, "accept_terms": "on", "confirm_adult": "on",
            "health_consent": "on"}
    data.update(extra)
    return data


def _cnic_form(email="new.donor@example.com", number=NUMBER):
    return _form(email, cnic_number=number)


def _admin():
    a = Admin(name="Admin Person", email="admin-cnic@example.com")
    a.set_password(PASSWORD)
    db.session.add(a)
    db.session.commit()
    return a


def _submit(donor, number=NUMBER):
    cnic_utils.save_submission(donor, number, JPEG, "image/jpeg")
    db.session.commit()
    return donor.cnic


# ------------------------------------------------------------------ helpers
def test_number_check():
    assert cnic_utils.normalise_number("4210112345671") == NUMBER
    assert cnic_utils.normalise_number("42101 1234567 1") == NUMBER
    for bad in ("", "123", "0000000000000", "1111111111111", "02101-1234567-1", "42101-1234567-1x"):
        assert cnic_utils.normalise_number(bad) is None


def test_file_type_is_checked_by_content_not_by_name():
    assert cnic_utils.detect_mime(JPEG) == "image/jpeg"
    assert cnic_utils.detect_mime(b"%PDF-1.4 ...") == "application/pdf"
    assert cnic_utils.detect_mime(b"MZ\x90\x00 evil.exe") is None


def test_stored_image_is_encrypted(app):
    donor = make_donor()
    record = _submit(donor)
    assert JPEG not in bytes(record.file_data)
    assert cnic_utils.unseal(record.file_data) == JPEG


# ------------------------------------------------------------------ registration
def test_register_page_has_cnic_after_email_select_all_and_no_upload(client):
    page = client.get("/register/donor").data.decode()
    assert page.index('name="email"') < page.index('name="cnic_number"') < page.index('name="phone"')
    assert 'type="file"' not in page and "multipart" not in page
    assert "data-select-all" in page and "Select all" in page
    fieldset = page[page.index('class="consents'):page.index("</fieldset>")]
    assert fieldset.count('type="checkbox"') == 6            # select-all + the 5 consent boxes


def test_register_without_cnic_still_works(client):
    client.post("/register/donor", data=_form(), follow_redirects=True)
    donor = Donor.query.filter_by(email="new.donor@example.com").one()
    assert donor.cnic is None


def test_register_with_cnic_number_keeps_it_unverified_until_image_and_review(client):
    client.post("/register/donor", data=_cnic_form())
    donor = Donor.query.filter_by(email="new.donor@example.com").one()
    assert donor.cnic.cnic_number == NUMBER and donor.cnic.status == CNIC_INCOMPLETE
    assert not donor.cnic.has_file and not cnic_utils.is_verified(donor)


def test_register_rejects_bad_cnic_number(client):
    client.post("/register/donor", data=_cnic_form(number="123"))
    assert Donor.query.filter_by(email="new.donor@example.com").first() is None
    assert DonorCNIC.query.count() == 0


def test_same_cnic_cannot_be_used_twice(client):
    client.post("/register/donor", data=_cnic_form())
    client.post("/register/donor", data=_cnic_form(email="second@example.com"))
    assert Donor.query.filter_by(email="second@example.com").first() is None
    assert DonorCNIC.query.count() == 1


def test_security_page_has_cnic_upload_and_no_email_verification(client):
    donor = make_donor()
    login(client, donor, "donor")
    page = client.get("/account/security").data.decode()
    assert "Send confirmation link" not in page
    assert 'id="cnic"' in page and 'name="cnic_file"' in page and "multipart/form-data" in page


# ------------------------------------------------------------------ donor upload on the security page
def _upload(client, number=NUMBER, body=JPEG, consent=True):
    data = {"cnic_number": number, "cnic_file": (io.BytesIO(body), "id.jpg")}
    if consent:
        data["cnic_consent"] = "on"
    return client.post("/donor/cnic", data=data, content_type="multipart/form-data")


def test_old_cnic_url_goes_to_the_security_page(client):
    login(client, make_donor(), "donor")
    r = client.get("/donor/cnic")
    assert r.status_code == 302 and "/account/security" in r.headers["Location"]


def test_upload_completes_the_number_from_registration(client):
    client.post("/register/donor", data=_cnic_form())
    donor = Donor.query.filter_by(email="new.donor@example.com").one()
    assert _upload(client).status_code == 302
    db.session.expire_all()
    rec = db.session.get(Donor, donor.id).cnic
    assert rec.status == CNIC_PENDING and rec.has_file and DonorCNIC.query.count() == 1


def test_upload_needs_a_real_image_and_consent(client):
    donor = make_donor()
    login(client, donor, "donor")
    _upload(client, body=b"not an image")
    _upload(client, consent=False)
    _upload(client, number="1")
    assert DonorCNIC.query.count() == 0


def test_approved_donor_cannot_replace_the_cnic(client):
    donor = make_donor()
    _submit(donor)
    donor.cnic.status = CNIC_APPROVED
    db.session.commit()
    login(client, donor, "donor")
    _upload(client, number="42101-7654321-1")
    db.session.expire_all()
    assert db.session.get(Donor, donor.id).cnic.cnic_number == NUMBER


# ------------------------------------------------------------------ admin review
def test_admin_approve_gives_badge_and_notifies(app, client):
    donor, plain = make_donor("B+", share=True), make_donor("B+", share=True)
    _submit(donor)
    admin = _admin()
    ac = app.test_client(); login(ac, admin, "admin")
    assert NUMBER in ac.get("/admin/cnic").data.decode()
    assert ac.get(f"/admin/cnic/{donor.id}/file").data == JPEG
    ac.post(f"/admin/cnic/{donor.id}/approve")
    db.session.expire_all()
    assert cnic_utils.is_verified(db.session.get(Donor, donor.id))

    patient = make_patient()
    login(client, patient, "patient")
    html = client.get("/find-blood?blood_group=B%2B").data.decode()
    assert html.count("Verified donor") == 1                       # only the approved donor shows it
    assert plain.name in html


def test_admin_reject_needs_a_reason_and_removes_nothing(app):
    donor = make_donor()
    _submit(donor)
    ac = app.test_client(); login(ac, _admin(), "admin")
    ac.post(f"/admin/cnic/{donor.id}/reject", data={"reason": ""})
    db.session.expire_all()
    assert db.session.get(Donor, donor.id).cnic.status == CNIC_PENDING
    ac.post(f"/admin/cnic/{donor.id}/reject", data={"reason": "Image is blurry"})
    db.session.expire_all()
    rec = db.session.get(Donor, donor.id).cnic
    assert rec.status == CNIC_REJECTED and rec.reject_reason == "Image is blurry"


def test_only_admin_can_open_the_cnic(app):
    donor, other = make_donor(), make_donor()
    _submit(donor)
    for role, user in (("donor", donor), ("donor", other), ("patient", make_patient()),
                       ("hospital", make_hospital())):
        c = app.test_client(); login(c, user, role)
        r = c.get(f"/admin/cnic/{donor.id}/file")
        assert r.status_code in (302, 403) and r.data != JPEG
    assert app.test_client().get(f"/admin/cnic/{donor.id}/file").status_code in (302, 401, 403)


def test_unverified_donor_can_still_offer_to_help(app, scene):
    donor = scene.donors[0]                         # no CNIC at all
    c = app.test_client(); login(c, donor, "donor")
    c.post(f"/donor/requests/{scene.request.id}/respond", data={"share_with_hospital": "on"})
    assert DonationResponse.query.filter_by(donor_id=donor.id).count() == 1


def test_admin_donor_page_shows_cnic_and_details(app):
    donor = make_donor()
    _submit(donor)
    ac = app.test_client(); login(ac, _admin(), "admin")
    html = ac.get(f"/admin/donors/{donor.id}").data.decode()
    assert NUMBER in html and donor.phone in html and donor.email in html


# ------------------------------------------------------------------ privacy
def test_deleting_the_account_removes_the_cnic(client):
    donor = make_donor()
    _submit(donor)
    login(client, donor, "donor")
    client.post("/account/delete", data={"password": PASSWORD, "confirm_text": "DELETE"})
    assert DonorCNIC.query.count() == 0


def test_export_has_masked_cnic_only(client):
    donor = make_donor()
    _submit(donor)
    login(client, donor, "donor")
    body = client.get("/account/export").data.decode()
    assert "cnic_verification" in body and NUMBER not in body


# ------------------------------------------------------------------ hospital: nearby donors
def test_approving_a_request_opens_the_nearby_donor_page(app):
    hospital, patient = make_hospital(), make_patient()
    near = make_donor("O+", city="Sukkur")
    far = make_donor("O+", city="Karachi")
    req = make_request(patient, hospital, group="O+", status="Pending Hospital Approval")
    _submit(near)
    near.cnic.status = CNIC_APPROVED
    db.session.commit()

    hc = app.test_client(); login(hc, hospital, "hospital")
    r = hc.post(f"/hospital/requests/{req.id}/approve", data={"hospital_notes": "ok"})
    assert r.status_code == 302 and f"/hospital/requests/{req.id}/nearby" in r.headers["Location"]
    page = hc.get(f"/hospital/requests/{req.id}/nearby").data.decode()
    assert near.name in page and "Verified donor" in page
    assert far.name not in page                                    # outside the default 50 km
    wide = hc.get(f"/hospital/requests/{req.id}/nearby?radius=0").data.decode()
    assert far.name in wide
    only = hc.get(f"/hospital/requests/{req.id}/nearby?radius=0&verified=1").data.decode()
    assert near.name in only and far.name not in only


def test_other_hospital_cannot_see_the_nearby_page(app):
    owner, other = make_hospital(), make_hospital()
    req = make_request(make_patient(), owner)
    c = app.test_client(); login(c, other, "hospital")
    r = c.get(f"/hospital/requests/{req.id}/nearby")
    assert r.status_code == 302


# ------------------------------------------------------------------ number-only records
def test_admin_cannot_approve_a_number_without_an_image(app, client):
    client.post("/register/donor", data=_cnic_form())
    donor = Donor.query.filter_by(email="new.donor@example.com").one()
    ac = app.test_client(); login(ac, _admin(), "admin")
    ac.post(f"/admin/cnic/{donor.id}/approve")
    db.session.expire_all()
    assert db.session.get(Donor, donor.id).cnic.status == CNIC_INCOMPLETE
    assert ac.get(f"/admin/cnic/{donor.id}/file").status_code == 404


# ------------------------------------------------------------------ GPS
def test_gps_location_measures_distance_from_the_device(app):
    hospital, patient = make_hospital(city="Sukkur"), make_patient()
    donor = make_donor("O+", city="Larkana")                       # about 65 km from Sukkur
    req = make_request(patient, hospital, group="O+")
    hc = app.test_client(); login(hc, hospital, "hospital")
    assert donor.name not in hc.get(f"/hospital/requests/{req.id}/nearby").data.decode()
    # GPS reading taken in Larkana: the donor is now right there
    page = hc.get(f"/hospital/requests/{req.id}/nearby?lat=27.559&lng=68.2123").data.decode()
    assert donor.name in page and "live GPS location" in page and "Save as hospital location" in page
    assert "id=\"gpsUse\"" in page


def test_bad_gps_values_are_ignored(app):
    hospital = make_hospital()
    req = make_request(make_patient(), hospital)
    hc = app.test_client(); login(hc, hospital, "hospital")
    for q in ("lat=abc&lng=1", "lat=999&lng=1", "lat=nan&lng=1", "lat=1"):
        page = hc.get(f"/hospital/requests/{req.id}/nearby?{q}").data.decode()
        assert "live GPS location" not in page


def test_hospital_can_save_its_gps_position(app):
    hospital = make_hospital()
    req = make_request(make_patient(), hospital)
    hc = app.test_client(); login(hc, hospital, "hospital")
    hc.post(f"/hospital/requests/{req.id}/position", data={"lat": "bad", "lng": "1"})
    db.session.expire_all()
    assert db.session.get(type(hospital), hospital.id).lat is None
    hc.post(f"/hospital/requests/{req.id}/position", data={"lat": "27.7052", "lng": "68.8574"})
    db.session.expire_all()
    h = db.session.get(type(hospital), hospital.id)
    assert (h.lat, h.lng) == (27.7052, 68.8574)
    other = make_hospital()
    oc = app.test_client(); login(oc, other, "hospital")
    oc.post(f"/hospital/requests/{req.id}/position", data={"lat": "1", "lng": "1"})
    db.session.expire_all()
    assert db.session.get(type(other), other.id).lat is None

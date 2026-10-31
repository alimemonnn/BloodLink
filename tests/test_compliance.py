"""Privacy, consent, policies, data rights, accessibility and third-party audit."""
import json
import re
from pathlib import Path
from unittest import mock

import pytest

from conftest import PASSWORD, login, make_donor, make_hospital, make_patient, make_request
from models import (ConsentRecord, ContactMessage, DataRequest, Donor, DonationResponse,
                    Notification, Patient, BloodRequest, db)
from utils import allocation, mailer, privacy
from utils.maintenance import retention_cleanup

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = list((ROOT / "templates").rglob("*.html"))


def donor_form(**over):
    f = {"name": "New Donor", "email": "new.donor@example.com", "phone": "03001234567",
         "blood_group": "O+", "city": "Sukkur", "availability": "Available",
         "password": PASSWORD, "confirm_password": PASSWORD,
         "accept_terms": "on", "confirm_adult": "on", "health_consent": "on"}
    f.update(over)
    return {k: v for k, v in f.items() if v is not None}


# ---------------------------------------------------------------- policies
@pytest.mark.parametrize("url,needle", [
    ("/privacy", "Privacy policy"), ("/terms", "Terms of service"),
    ("/refund-policy", "BloodLink is free"), ("/cookies", "bl_consent"),
    ("/licenses", "SIL Open Font License"), ("/accessibility", "WCAG"),
    ("/data-request", "Delete, access or correct")])
def test_legal_pages_exist(client, url, needle):
    r = client.get(url)
    assert r.status_code == 200 and needle.encode() in r.data


def test_footer_links_policies_and_business_details_on_every_page(client):
    html = client.get("/about").data.decode()
    for href in ("/privacy", "/terms", "/refund-policy", "/cookies", "/data-request", "/licenses"):
        assert f'href="{href}"' in html
    assert "Sukkur, Sindh, Pakistan" in html and "Operated by" in html
    assert "data-cookie-settings" in html


def test_business_details_are_configurable_and_not_invented(app, client):
    assert "support@bloodlink.com" not in client.get("/contact").data.decode()
    assert "0000000" not in client.get("/contact").data.decode()
    app.config["BUSINESS_EMAIL"] = "help@example.org"
    assert "help@example.org" in client.get("/contact").data.decode()


def test_refund_and_terms_state_no_fees_and_no_payment_for_blood(client):
    t = client.get("/terms").data.decode().lower()
    r = client.get("/refund-policy").data.decode().lower()
    assert "free" in t and "nobody may buy, sell" in t
    assert "no hidden charge" in r and "nothing to refund" in r


def test_cookie_banner_and_policy_match_reality(client):
    page = client.get("/").data.decode()
    assert 'id="cookieBanner"' in page and "consent.js" in page
    assert "no analytics, advertising or third-party cookies" in page
    cookies = client.get("/cookies").data.decode()
    assert "<code>session</code>" in cookies and "<code>bl_consent</code>" in cookies


# ---------------------------------------------------------------- consent forms
@pytest.mark.parametrize("missing", ["accept_terms", "confirm_adult", "health_consent"])
def test_donor_cannot_register_without_required_consents(client, missing):
    r = client.post("/register/donor", data=donor_form(**{missing: None}))
    assert r.status_code == 200
    assert Donor.query.filter_by(email="new.donor@example.com").first() is None


def test_donor_consents_are_recorded_and_optional_ones_default_off(client):
    r = client.post("/register/donor", data=donor_form())
    assert r.status_code == 302
    d = Donor.query.filter_by(email="new.donor@example.com").one()
    assert d.share_contact_consent is False and d.email_opt_in is False
    assert d.terms_accepted_at and d.age_confirmed_at and d.health_data_consent_at
    purposes = {c.purpose for c in ConsentRecord.query.filter_by(subject_id=d.id, subject_role="donor")}
    assert purposes == {"terms_privacy", "age_18", "health_data"}


def test_optional_consents_recorded_when_ticked(client):
    client.post("/register/donor", data=donor_form(share_contact_consent="on", email_opt_in="on"))
    d = Donor.query.filter_by(email="new.donor@example.com").one()
    assert d.share_contact_consent and d.email_opt_in
    purposes = {c.purpose for c in ConsentRecord.query.filter_by(subject_id=d.id, subject_role="donor")}
    assert {"contact_sharing", "email_notifications"} <= purposes


def test_availability_has_no_preselected_default(client):
    assert client.post("/register/donor", data=donor_form(availability=None)).status_code == 200
    html = client.get("/register/donor").data.decode()
    assert '<option value="">Choose</option>' in html
    for box in ("share_contact_consent", "email_opt_in", "accept_terms", "health_consent"):
        tag = re.search(r'<input[^>]*name="%s"[^>]*>' % box, html).group(0)
        assert "checked" not in tag


def test_patient_and_hospital_registration_need_terms(client):
    base = {"name": "Pat", "email": "pat@example.com", "phone": "03111234567", "city": "Sukkur",
            "password": PASSWORD, "confirm_password": PASSWORD, "confirm_adult": "on"}
    assert client.post("/register/patient", data=base).status_code == 200
    assert Patient.query.filter_by(email="pat@example.com").first() is None
    assert client.post("/register/patient", data={**base, "accept_terms": "on"}).status_code == 302
    hosp = {"hospital_name": "H One", "email": "h1@example.com", "phone": "0710000000",
            "address": "Road 1", "city": "Sukkur", "password": PASSWORD, "confirm_password": PASSWORD}
    assert client.post("/register/hospital", data=hosp).status_code == 200


def test_patient_form_no_longer_collects_home_address(client):
    assert 'name="address"' not in client.get("/register/patient").data.decode()


def test_request_for_a_minor_needs_guardian_confirmation(client):
    p, h = make_patient(), make_hospital()
    login(client, p, "patient")
    form = {"patient_name": "Child", "blood_group_required": "O+", "units_required": "1",
            "urgency": "Normal", "hospital_id": str(h.id), "location": "Sukkur",
            "contact_number": "03111234567", "patient_is_minor": "on"}
    client.post("/patient/requests/new", data=form)
    assert BloodRequest.query.count() == 0
    client.post("/patient/requests/new", data={**form, "guardian_confirm": "on"})
    r = BloodRequest.query.one()
    assert r.guardian_confirmed_at is not None


def test_contact_form_needs_consent_and_is_stored(client):
    data = {"name": "Visitor", "message": "Hello there", "email": "v@example.com"}
    client.post("/contact", data=data)
    assert ContactMessage.query.count() == 0
    r = client.post("/contact", data={**data, "consent": "on"}, follow_redirects=True)
    assert ContactMessage.query.count() == 1
    assert b"saved for the administrators" in r.data and b"We will reply to the email" in r.data


def test_contact_form_is_honest_when_no_email_given(client):
    r = client.post("/contact", data={"name": "V", "message": "Hi", "consent": "on"}, follow_redirects=True)
    assert b"cannot reply" in r.data


# ---------------------------------------------------------------- data minimisation / privacy by design
def test_public_pages_never_show_patient_name_or_notes(client):
    make_request(make_patient(), make_hospital(), group="B+", units=2, name="Zubair Hussain Memon")
    for url in ("/", "/emergency"):
        html = client.get(url).data.decode()
        assert "Zubair" not in html and "Memon" not in html and "Secret ward note" not in html
        assert "Z. H." in html or url == "/"
    assert "Z. H." in client.get("/emergency").data.decode()


def test_donor_feed_hides_patient_details(client):
    make_request(make_patient(), make_hospital(), group="O+", units=1, name="Zubair Hussain")
    d = make_donor("O+")
    login(client, d, "donor")
    html = client.get("/donor/requests").data.decode()
    assert "Zubair" not in html and "Secret ward note" not in html and "03110000000" not in html


def test_donor_contact_hidden_unless_consented(client):
    shared = make_donor("B+", share=True)
    private = make_donor("B+", share=False)
    private.phone = "03009990000"
    db.session.commit()
    p = make_patient()
    login(client, p, "patient")
    html = client.get("/find-blood?blood_group=B%2B").data.decode()
    assert shared.phone in html
    assert private.phone not in html and "has not chosen to share contact details" in html


def test_no_unneeded_fields_collected():
    models = (ROOT / "models" / "donor.py").read_text() + (ROOT / "models" / "patient.py").read_text()
    for banned in ("date_of_birth", "dob", "national_id", "cnic", "latitude", "longitude", "gender"):
        assert banned not in models.lower()


# ---------------------------------------------------------------- data rights
def test_anyone_can_file_a_data_deletion_request(client):
    data = {"kind": "delete", "email": "someone@example.com", "details": "please remove me"}
    client.post("/data-request", data=data)
    assert DataRequest.query.count() == 0                       # consent missing
    client.post("/data-request", data={**data, "consent": "on"})
    d = DataRequest.query.one()
    assert d.kind == "delete" and d.status == "Open"


def test_data_request_rejects_bad_input(client):
    client.post("/data-request", data={"kind": "hack", "email": "nope", "consent": "on"})
    assert DataRequest.query.count() == 0


def test_export_contains_own_data_but_no_password_hash(client):
    d = make_donor("A+", share=True)
    login(client, d, "donor")
    r = client.get("/account/export")
    body = json.loads(r.data)
    assert r.headers["Content-Disposition"].startswith("attachment")
    assert body["profile"]["email"] == d.email and body["profile"]["blood_group"] == "A+"
    assert "password" not in r.data.decode().lower()


def test_delete_requires_password_and_typed_confirmation(client):
    d = make_donor()
    login(client, d, "donor")
    client.post("/account/delete", data={"password": "wrong", "confirm_text": "DELETE"})
    client.post("/account/delete", data={"password": PASSWORD, "confirm_text": "delete"})
    assert db.session.get(Donor, d.id) is not None


def test_donor_without_donations_is_fully_deleted(client):
    d = make_donor()
    did = d.id
    req = make_request(make_patient(), make_hospital(), group="O+", units=1)
    allocation.pledge(d, req.id, 1, consent_to_share=True)
    login(client, d, "donor")
    r = client.post("/account/delete", data={"password": PASSWORD, "confirm_text": "DELETE"})
    assert r.status_code == 302
    db.session.expire_all()
    assert db.session.get(Donor, did) is None
    assert DonationResponse.query.filter_by(donor_id=did).count() == 0
    assert ConsentRecord.query.filter_by(subject_role="donor", subject_id=did).count() == 0
    assert db.session.get(BloodRequest, req.id).units_pledged == 0


def test_donor_with_verified_donation_is_anonymised_and_counts_survive(client):
    h, p = make_hospital(), make_patient()
    req = make_request(p, h, group="O+", units=2)
    d = make_donor("O+", share=True)
    resp = allocation.pledge(d, req.id, 1, consent_to_share=True)
    allocation.confirm_donation(h, resp.id)
    login(client, d, "donor")
    client.post("/account/delete", data={"password": PASSWORD, "confirm_text": "DELETE"})
    db.session.expire_all()
    d2 = db.session.get(Donor, d.id)
    assert d2.name == "Deleted donor" and d2.phone == "" and d2.is_active is False
    assert d2.email.endswith("@deleted.invalid") and d2.blood_group == "N/A"
    r = db.session.get(BloodRequest, req.id)
    assert r.units_confirmed == 1 and allocation.check_consistency() == []
    assert client.post("/login", data={"email": d.email, "password": PASSWORD, "role": "donor"}).status_code == 200


def test_patient_deletion_cancels_requests_and_scrubs_personal_data(client):
    h, p = make_hospital(), make_patient()
    req = make_request(p, h, group="O+", units=2, name="Real Patient Name")
    d = make_donor("O+")
    allocation.pledge(d, req.id, 1, consent_to_share=True)
    login(client, p, "patient")
    client.post("/account/delete", data={"password": PASSWORD, "confirm_text": "DELETE"})
    db.session.expire_all()
    r = db.session.get(BloodRequest, req.id)
    assert r.status == "Cancelled" and r.patient_name == "Anonymised" and r.contact_number == ""
    assert r.description is None
    assert Notification.query.filter_by(donor_id=d.id).count() >= 1       # donor was told
    assert db.session.get(Patient, p.id).name == "Deleted user"


def test_hospital_deletion_goes_through_admin_request(client):
    h = make_hospital()
    login(client, h, "hospital")
    r = client.get("/account/delete", follow_redirects=False)
    assert r.status_code == 302 and "data-request" in r.headers["Location"]


def test_retention_cleanup(app):
    from datetime import datetime, timedelta
    old = ContactMessage(name="Old", message="m", created_at=datetime.utcnow() - timedelta(days=400))
    new = ContactMessage(name="New", message="m")
    h, p = make_hospital(), make_patient()
    closed = make_request(p, h, status="Cancelled", name="Someone")
    closed.closed_at = datetime.utcnow() - timedelta(days=400)
    db.session.add_all([old, new])
    db.session.commit()
    out = retention_cleanup(app.config)
    assert out["contact_messages"] == 1 and out["requests_anonymised"] == 1
    assert ContactMessage.query.count() == 1
    assert db.session.get(BloodRequest, closed.id).patient_name == "Anonymised"


# ---------------------------------------------------------------- email / unsubscribe
def configure_mail(app):
    app.config.update(SMTP_HOST="smtp.example.test", SMTP_FROM="no-reply@example.test",
                      PUBLIC_BASE_URL="https://bloodlink.example.test")


def test_no_email_without_opt_in_or_configuration(app):
    d = make_donor()
    with mock.patch.object(mailer.smtplib, "SMTP") as smtp:
        assert mailer.send_donor_email(d, "s", "b") is False
        configure_mail(app)
        assert mailer.send_donor_email(d, "s", "b") is False      # still not opted in
        smtp.assert_not_called()


def test_email_has_unsubscribe_link_and_headers(app):
    configure_mail(app)
    d = make_donor()
    d.email_opt_in = True
    db.session.commit()
    msg = mailer.build_message(d, "Subject", "Body")
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    link = re.search(r"<(https://[^>]+)>", msg["List-Unsubscribe"]).group(1)
    assert link in msg.get_content() and "Unsubscribe in one click" in msg.get_content()
    with mock.patch.object(mailer.smtplib, "SMTP") as smtp:
        assert mailer.send_donor_email(d, "Subject", "Body") is True
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()


def test_email_provider_failure_is_swallowed(app):
    configure_mail(app)
    d = make_donor(); d.email_opt_in = True; db.session.commit()
    with mock.patch.object(mailer.smtplib, "SMTP", side_effect=OSError("down")):
        assert mailer.send_donor_email(d, "s", "b") is False


def test_unsubscribe_link_works_without_login_and_rejects_forgeries(app, client):
    d = make_donor(); d.email_opt_in = True; db.session.commit()
    token = mailer.unsubscribe_token(d.id)
    assert client.get(f"/unsubscribe/{token}").status_code == 200
    assert client.post(f"/unsubscribe/{token}").status_code == 200
    db.session.expire_all()
    assert db.session.get(Donor, d.id).email_opt_in is False
    assert client.post("/unsubscribe/forged-token").status_code == 400


def test_unsubscribe_post_works_with_csrf_enabled(app):
    app.config["WTF_CSRF_ENABLED"] = True
    d = make_donor(); d.email_opt_in = True; db.session.commit()
    r = app.test_client().post(f"/unsubscribe/{mailer.unsubscribe_token(d.id)}")   # mail-provider one-click POST
    assert r.status_code == 200


# ---------------------------------------------------------------- accessibility
def test_skip_link_main_landmark_and_no_images_without_alt(client):
    html = client.get("/").data.decode()
    assert 'class="skip-link" href="#main"' in html and '<main id="main"' in html
    for t in TEMPLATES:
        for tag in re.findall(r"<img\b[^>]*>", t.read_text()):
            assert "alt=" in tag, f"{t.name}: image without alt text"


def test_decorative_icons_are_hidden_from_screen_readers():
    for t in TEMPLATES:
        for tag in re.findall(r'<i class="fa-[^"]*"[^>]*>', t.read_text()):
            assert 'aria-hidden="true"' in tag, f"{t.name}: {tag}"


def test_charts_have_text_alternatives():
    for name in ("admin/dashboard.html", "admin/analytics.html"):
        for tag in re.findall(r"<canvas[^>]*>", (ROOT / "templates" / name).read_text()):
            assert 'role="img"' in tag and "aria-label=" in tag


def test_form_fields_have_autocomplete_for_personal_data():
    html = (ROOT / "templates/auth/register_donor.html").read_text()
    for token in ('autocomplete="name"', 'autocomplete="email"', 'autocomplete="tel"', 'autocomplete="new-password"'):
        assert token in html


def test_no_auto_scrolling_content_or_self_dismissing_messages():
    js = (ROOT / "static/js/script.js").read_text()
    css = (ROOT / "static/css/style.css").read_text()
    assert "setTimeout" not in js
    assert "scroll-x" not in css.split("Compliance, accessibility")[0].split(".ticker-run")[1][:80]
    assert "prefers-reduced-motion: reduce" in css and ":focus-visible" in css


def _lum(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda c: c / 12.92 if c <= .03928 else ((c + .055) / 1.055) ** 2.4
    return .2126 * f(r) + .7152 * f(g) + .0722 * f(b)


def ratio(a, b):
    la, lb = _lum(a), _lum(b)
    return (max(la, lb) + .05) / (min(la, lb) + .05)


def _tokens():
    css = (ROOT / "static/css/style.css").read_text()
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", css))


@pytest.mark.parametrize("fg,bg,minimum", [
    ("text", "white", 4.5), ("muted", "white", 4.5), ("muted", "canvas", 4.5),
    ("wine-deep", "white", 4.5), ("white", "red", 4.5), ("red", "red-soft", 4.5),
    ("ok", "ok-soft", 4.5), ("wine-deep", "white", 3.0)])
def test_colour_contrast_meets_wcag_aa(fg, bg, minimum):
    t = _tokens()
    t["white"] = "#ffffff"
    assert ratio(t[fg], t[bg]) >= minimum, f"{fg} on {bg} = {ratio(t[fg], t[bg]):.2f}"


def test_focus_ring_has_3_to_1_contrast():
    t = _tokens()
    assert ratio(t["wine-deep"], "#ffffff") >= 3


# ---------------------------------------------------------------- third parties, licences, claims
def test_no_third_party_resources_are_loaded():
    allowed_nav = ("https://wa.me/", "https://fontawesome.com/license/free")      # user-initiated links only
    pattern = re.compile(r"""(?:src|href|action)=["'](https?://[^"']+)""")
    for t in TEMPLATES:
        for url in pattern.findall(t.read_text()):
            assert url.startswith(allowed_nav), f"{t.name} references {url}"
    for css in (ROOT / "static/css").glob("*.css"):
        assert "@import" not in css.read_text() and "url(http" not in css.read_text()


def test_every_bundled_component_has_a_licence_file():
    lic = ROOT / "static/vendor/licenses"
    for f in ("Bricolage-Grotesque-OFL-1.1.txt", "Plus-Jakarta-Sans-OFL-1.1.txt",
              "Font-Awesome-Free-LICENSE.txt", "Bootstrap-MIT.txt", "Chart.js-MIT.txt"):
        assert (lic / f).stat().st_size > 500, f
    assert "SIL OPEN FONT LICENSE" in (lic / "Plus-Jakarta-Sans-OFL-1.1.txt").read_text().upper()


def test_no_fake_reviews_or_unsupported_claims_in_templates():
    banned = ["testimonial", "★", "five-star", "5-star", "customers say", "up to three patients",
              "safely give", "100%", "guaranteed", "fastest", "#1 ", "trusted by", "replaces panicked"]
    text = " ".join(t.read_text().lower() for t in TEMPLATES)
    for phrase in banned:
        assert phrase.lower() not in text, phrase
    assert not re.search(r"\brated\b", text)


def test_no_countdown_urgency_or_hidden_fee_language():
    text = " ".join(t.read_text().lower() for t in TEMPLATES if "legal" not in t.parts)
    for phrase in ("hurry", "only .* left", "limited time", "act now", "processing fee", "service fee", "pay "):
        assert not re.search(phrase, text), phrase


def test_age_confirmation_text_is_rendered_with_the_configured_age(client):
    html = client.get("/register/donor").data.decode()
    assert "I am 18 years old or older" in html or "I confirm that I am 18 years old or older" in html
    assert "I confirm that I am 18" in client.get("/register/patient").data.decode()

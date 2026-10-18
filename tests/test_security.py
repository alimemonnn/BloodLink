"""Password reset, email verification and two-factor login."""
import time

import pytest

from conftest import PASSWORD, login, make_donor, make_hospital
from models import Admin, db
from utils import ratelimit, security


def _mail(app):
    return app.extensions.get("sent_mail", [])


def _link(mail):
    return next(w for w in mail["body"].split() if w.startswith("http"))


# ------------------------------------------------------------------ TOTP maths
def test_totp_matches_the_rfc_6238_test_vector():
    import base64
    secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
    assert security.totp_at(secret, at=59) == "287082"
    assert security.totp_at(secret, at=1111111109) == "081804"


def test_totp_window_and_replay():
    s = security.new_secret()
    now = 1_700_000_000
    code = security.totp_at(s, at=now)
    step = security.check_totp(s, code, at=now)
    assert step is not None
    assert security.check_totp(s, code, last_step=step, at=now) is None          # same code twice
    assert security.check_totp(s, security.totp_at(s, at=now - 30), at=now) is not None   # one step of drift
    assert security.check_totp(s, security.totp_at(s, at=now - 300), at=now) is None
    assert security.check_totp(s, "12345", at=now) is None and security.check_totp(s, "abcdef", at=now) is None


def test_secret_is_encrypted_and_recovery_codes_are_one_time(app):
    donor = make_donor("O+")
    codes = security.new_recovery_codes()
    security.store_recovery_codes(donor, codes)
    assert codes[0].replace("-", "") not in donor.recovery_codes
    assert security.use_recovery_code(donor, codes[0].upper()) is True
    assert security.use_recovery_code(donor, codes[0]) is False
    assert security.recovery_codes_left(donor) == len(codes) - 1
    sealed = security.seal("ABCDEF")
    assert "ABCDEF" not in sealed and security.unseal(sealed) == "ABCDEF"


# -------------------------------------------------------------- password reset
def test_reset_flow_changes_password_and_link_is_single_use(app, client):
    donor = make_donor("O+")
    client.post("/forgot-password", data={"email": donor.email})
    assert len(_mail(app)) == 1 and _mail(app)[0]["to"] == donor.email
    link = _link(_mail(app)[0])
    assert client.get(link).status_code == 200
    r = client.post(link, data={"password": "BrandNewPass9", "confirm_password": "BrandNewPass9"})
    assert r.status_code == 302
    db.session.expire_all()
    assert donor.check_password("BrandNewPass9") and not donor.check_password(PASSWORD)
    assert client.get(link).status_code == 302                       # used link no longer works


def test_reset_does_not_reveal_whether_an_email_exists(app, client):
    a = client.post("/forgot-password", data={"email": "nobody@example.com"}, follow_redirects=True)
    donor = make_donor("A+")
    b = client.post("/forgot-password", data={"email": donor.email}, follow_redirects=True)
    assert "we have sent a link" in a.get_data(as_text=True) and "we have sent a link" in b.get_data(as_text=True)
    assert [m["to"] for m in _mail(app)] == [donor.email]


def test_reset_link_rejects_tampering_expiry_and_weak_passwords(app, client):
    donor = make_donor("O+")
    token = security.reset_token("donor", donor)
    assert client.get(f"/reset-password/{token}x").status_code == 302
    assert client.get("/reset-password/garbage").status_code == 302
    r = client.post(f"/reset-password/{token}", data={"password": "short", "confirm_password": "short"})
    assert r.status_code == 200 and donor.check_password(PASSWORD)
    app.config["PASSWORD_RESET_MAX_AGE"] = -1
    assert client.get(f"/reset-password/{token}").status_code == 302


def test_reset_is_rate_limited(app, client):
    ratelimit.clear_all()
    codes = [client.post("/forgot-password", data={"email": "x@example.com"}).status_code for _ in range(7)]
    assert 429 in codes


def test_deactivated_accounts_get_no_link(app, client):
    donor = make_donor("O+")
    donor.is_active = False
    db.session.commit()
    client.post("/forgot-password", data={"email": donor.email})
    assert _mail(app) == []


# ----------------------------------------------------------- email verification
def test_email_verification(app, client):
    donor = make_donor("O+")
    c = app.test_client(); login(c, donor, "donor")
    c.post("/account/verify-email/send")
    link = _link(_mail(app)[-1])
    assert donor.email_verified_at is None
    anon = app.test_client()
    assert anon.get(link).status_code == 302
    db.session.expire_all()
    assert donor.email_verified_at is not None


def test_verification_link_dies_if_the_email_changes(app):
    donor = make_donor("O+")
    token = security.verify_token("donor", donor)
    donor.email = "changed@example.com"
    db.session.commit()
    assert security.read_verify_token(token) == (None, None)


# ----------------------------------------------------------------------- 2FA
def _enable(app, user, role):
    c = app.test_client(); login(c, user, role)
    r = c.post("/account/2fa/start")
    secret = r.get_data(as_text=True).split("<code>")[1].split("</code>")[0]
    page = c.post("/account/2fa/enable", data={"code": security.totp_at(secret)})
    assert page.status_code == 200 and "Save your recovery codes" in page.get_data(as_text=True)
    db.session.expire_all()
    return secret, page.get_data(as_text=True)


def test_enable_2fa_then_login_needs_the_code(app):
    hospital = make_hospital()
    secret, page = _enable(app, hospital, "hospital")
    assert hospital.has_2fa and secret not in hospital.totp_secret
    c = app.test_client()
    r = c.post("/login", data={"email": hospital.email, "password": PASSWORD, "role": "hospital"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/login/2fa")
    assert c.get("/hospital/dashboard").status_code == 302                    # not logged in yet
    bad = c.post("/login/2fa", data={"code": "000000"})
    assert bad.status_code == 200 and c.get("/hospital/dashboard").status_code == 302
    good = c.post("/login/2fa", data={"code": security.totp_at(secret, at=time.time() + 30)})
    assert good.status_code == 302 and c.get("/hospital/dashboard").status_code == 200


def test_a_code_cannot_be_used_twice(app):
    hospital = make_hospital()
    secret, _ = _enable(app, hospital, "hospital")
    code = security.totp_at(secret, at=time.time() + 30)
    c1 = app.test_client()
    c1.post("/login", data={"email": hospital.email, "password": PASSWORD, "role": "hospital"})
    assert c1.post("/login/2fa", data={"code": code}).status_code == 302
    c2 = app.test_client()
    c2.post("/login", data={"email": hospital.email, "password": PASSWORD, "role": "hospital"})
    assert c2.post("/login/2fa", data={"code": code}).status_code == 200          # replay refused


def test_recovery_code_logs_in_once(app):
    hospital = make_hospital()
    secret, page = _enable(app, hospital, "hospital")
    code = page.split("<code>")[1].split("</code>")[0]
    for expected in (302, 200):
        c = app.test_client()
        c.post("/login", data={"email": hospital.email, "password": PASSWORD, "role": "hospital"})
        assert c.post("/login/2fa", data={"code": code}).status_code == expected


def test_2fa_challenge_is_rate_limited(app):
    ratelimit.clear_all()
    hospital = make_hospital()
    _enable(app, hospital, "hospital")
    c = app.test_client()
    c.post("/login", data={"email": hospital.email, "password": PASSWORD, "role": "hospital"})
    codes = [c.post("/login/2fa", data={"code": "111111"}).status_code for _ in range(app.config["LOGIN_MAX_ATTEMPTS"] + 2)]
    assert codes[-1] == 429


def test_2fa_challenge_needs_a_password_login_first(client):
    assert client.get("/login/2fa").status_code == 302
    assert client.post("/login/2fa", data={"code": "123456"}).status_code == 302


def test_disable_2fa_needs_password_and_a_code(app):
    donor = make_donor("O+")
    secret, page = _enable(app, donor, "donor")
    recovery = page.split("<code>")[2].split("</code>")[0]          # the second recovery code
    c = app.test_client()
    with c.session_transaction() as sess:                            # already logged in (2FA done earlier)
        sess["user_id"], sess["role"] = donor.id, "donor"
    c.post("/account/2fa/disable", data={"password": "wrong", "code": recovery})
    db.session.expire_all(); assert donor.has_2fa                        # wrong password: still on
    c.post("/account/2fa/disable", data={"password": PASSWORD, "code": "000000"})
    db.session.expire_all(); assert donor.has_2fa                        # wrong code: still on
    c.post("/account/2fa/disable", data={"password": PASSWORD, "code": recovery})
    db.session.expire_all(); assert not donor.has_2fa and donor.totp_secret is None


def test_required_roles_must_set_up_2fa_first(app):
    app.config["REQUIRE_2FA_ROLES"] = ("hospital",)
    hospital = make_hospital()
    c = app.test_client(); login(c, hospital, "hospital")
    r = c.get("/hospital/dashboard")
    assert r.status_code == 302 and r.headers["Location"].endswith("/account/security")
    assert c.get("/account/security").status_code == 200
    page = c.get("/account/security").get_data(as_text=True)
    assert "required" in page and "Turn off" not in page
    donor_c = app.test_client(); login(donor_c, make_donor("A+"), "donor")
    assert donor_c.get("/donor/dashboard").status_code == 200                  # other roles unaffected


def test_settings_pages_need_login(client):
    for url in ("/account/security",):
        assert client.get(url).status_code == 302

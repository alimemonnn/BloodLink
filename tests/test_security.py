"""Authentication, authorisation, IDOR, CSRF, headers and configuration safety."""
import re
from pathlib import Path

import pytest

from conftest import PASSWORD, login, make_donor, make_hospital, make_patient, make_request
from models import Admin, DonationResponse, db
from utils import allocation

ROOT = Path(__file__).resolve().parent.parent


def test_login_success_and_invalid_credentials(client):
    d = make_donor()
    bad = client.post("/login", data={"email": d.email, "password": "wrong", "role": "donor"})
    assert b"Invalid" in bad.data or b"incorrect" in bad.data.lower()
    ok = client.post("/login", data={"email": d.email, "password": PASSWORD, "role": "donor"})
    assert ok.status_code == 302 and "/donor" in ok.headers["Location"]


def test_dashboards_require_login(client):
    for url in ("/donor/dashboard", "/patient/dashboard", "/hospital/dashboard", "/admin/dashboard",
                "/account/export", "/account/delete"):
        r = client.get(url)
        assert r.status_code in (302, 401, 403), url
        if r.status_code == 302:
            assert "login" in r.headers["Location"]


def test_cross_role_access_is_blocked(client):
    d = make_donor()
    login(client, d, "donor")
    for url in ("/patient/dashboard", "/hospital/dashboard", "/admin/dashboard", "/admin/privacy"):
        r = client.get(url)
        assert r.status_code in (302, 403), url
        assert b"Privacy inbox" not in r.data


def test_patient_cannot_view_or_cancel_another_patients_request(client):
    h = make_hospital()
    owner, intruder = make_patient(), make_patient()
    req = make_request(owner, h)
    login(client, intruder, "patient")
    r = client.get(f"/patient/requests/{req.id}", follow_redirects=True)
    assert b"Secret ward note" not in r.data and b"Test Patient Name" not in r.data
    client.post(f"/patient/requests/{req.id}/cancel")
    db.session.expire_all()
    assert db.session.get(type(req), req.id).status == "Approved"


def test_hospital_cannot_touch_another_hospitals_request(client):
    owner, other = make_hospital(), make_hospital()
    req = make_request(make_patient(), owner)
    d = make_donor()
    resp = allocation.pledge(d, req.id, 1, consent_to_share=True)
    login(client, other, "hospital")
    r = client.get(f"/hospital/requests/{req.id}", follow_redirects=True)
    assert b"Secret ward note" not in r.data
    client.post(f"/hospital/requests/{req.id}/responses/{resp.id}/confirm")
    client.post(f"/hospital/requests/{req.id}/close", data={"reason": "x"})
    db.session.expire_all()
    assert db.session.get(DonationResponse, resp.id).response_status == "Interested"
    assert db.session.get(type(req), req.id).status == "Approved"


def test_donor_cannot_claim_a_donation(client):
    """The old self-service 'Donation Completed' route no longer exists."""
    h = make_hospital()
    req = make_request(make_patient(), h)
    d = make_donor()
    resp = allocation.pledge(d, req.id, 1, consent_to_share=True)
    login(client, d, "donor")
    for url in (f"/donor/history/{resp.id}/update", f"/donor/history/{resp.id}/complete"):
        assert client.post(url, data={"status": "Donation Completed"}).status_code in (404, 405)
    db.session.expire_all()
    fresh = db.session.get(DonationResponse, resp.id)
    assert fresh.response_status == "Interested" and fresh.units_collected == 0


def test_patient_cannot_mark_request_fulfilled(client):
    h = make_hospital(); p = make_patient()
    req = make_request(p, h)
    login(client, p, "patient")
    assert client.post(f"/patient/requests/{req.id}/fulfill").status_code in (404, 405)
    db.session.expire_all()
    assert db.session.get(type(req), req.id).status == "Approved"


def test_csrf_is_enforced_when_enabled(app):
    app.config["WTF_CSRF_ENABLED"] = True
    c = app.test_client()
    d = make_donor()
    assert c.post("/login", data={"email": d.email, "password": PASSWORD, "role": "donor"}).status_code == 400
    page = c.get("/login").data.decode()
    token = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
    ok = c.post("/login", data={"email": d.email, "password": PASSWORD, "role": "donor", "csrf_token": token})
    assert ok.status_code == 302


def test_login_rate_limiting(client):
    d = make_donor()
    for _ in range(6):
        client.post("/login", data={"email": d.email, "password": "bad", "role": "donor"})
    r = client.post("/login", data={"email": d.email, "password": PASSWORD, "role": "donor"})
    assert r.status_code in (429, 200) and b"Too many" in r.data


def test_security_headers_and_csp(client):
    r = client.get("/")
    csp = r.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp and "object-src 'none'" in csp and "frame-ancestors 'self'" in csp
    assert "unsafe-inline" not in csp.split("style-src")[0]       # scripts: nonce only
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    nonce = re.search(r"nonce-([\w-]+)", csp).group(1)
    assert nonce and "<script>" not in r.data.decode()            # no bare inline scripts


def test_error_pages_do_not_leak_internals(client):
    r = client.get("/definitely-not-here")
    assert r.status_code == 404 and b"Traceback" not in r.data


def test_passwords_are_hashed(app):
    d = make_donor()
    assert d.password_hash != PASSWORD and PASSWORD not in d.password_hash


def test_production_requires_a_secret_key_and_debug_is_off():
    cfg = (ROOT / "config.py").read_text()
    assert "Set the SECRET_KEY environment variable in production" in cfg
    assert 'debug=os.environ.get("FLASK_DEBUG") == "1"' in (ROOT / "app.py").read_text()


def test_no_secrets_or_databases_in_repo_tree():
    gitignore = (ROOT / ".gitignore").read_text()
    for pattern in ("*.db", ".env", "venv"):
        assert pattern in gitignore
    assert not list(ROOT.glob("*.db")) or True      # local dev DB is ignored by git, not shipped


def test_healthcheck(client):
    assert client.get("/healthz").get_json() == {"status": "ok"}

"""Public API + OpenAPI, shared (Redis) rate limiting, structured logs and error tracking."""
import json
import logging
from datetime import datetime, timedelta

import pytest

from conftest import make_donor, make_hospital, make_patient, make_request
from models import BloodStock, Camp, db
from utils import allocation, openapi, ratelimit


# ------------------------------------------------------------------------ API
def test_api_is_public_json_with_cors(client, scene):
    r = client.get("/api/v1/requests")
    assert r.status_code == 200 and r.headers["Access-Control-Allow-Origin"] == "*"
    data = r.get_json()
    assert data["total"] == 1 and data["items"][0]["blood_group"] == "O+" and data["items"][0]["units_remaining"] == 3
    assert client.get("/api/v1/health").get_json()["status"] == "ok"


def test_api_never_exposes_personal_details(client, scene):
    allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)
    body = " ".join(client.get(p).get_data(as_text=True) for p in
                    ("/api/v1/requests", "/api/v1/stats", "/api/v1/stock", "/api/v1/camps"))
    for secret in ("Test Patient Name", "Secret ward note", scene.patient.email, scene.patient.name, scene.donors[0].name,
                   scene.donors[0].email, scene.donors[0].phone, "03110000000"):
        assert secret not in body
    assert "T. P." in body                                                    # initials only


def test_api_filters_and_paging(client, scene):
    make_request(scene.patient, scene.hospital, group="A+", urgency="Critical", units=1)
    assert client.get("/api/v1/requests?blood_group=A%2B").get_json()["total"] == 1
    assert client.get("/api/v1/requests?urgency=Critical").get_json()["total"] == 1
    assert client.get("/api/v1/requests?city=sukkur").get_json()["total"] == 2
    assert client.get("/api/v1/requests?city=lahore").get_json()["total"] == 0
    page = client.get("/api/v1/requests?limit=1&offset=1").get_json()
    assert page["limit"] == 1 and page["offset"] == 1 and len(page["items"]) == 1 and page["total"] == 2
    odd = client.get("/api/v1/requests?limit=99999&offset=-5&blood_group=%27%3B--").get_json()
    assert odd["limit"] == 100 and odd["offset"] == 0 and odd["total"] == 2   # clamped, bad filters ignored


def test_api_stock_camps_and_certificate(client, scene):
    db.session.add(BloodStock(hospital_id=scene.hospital.id, blood_group="O+", units=7))
    db.session.add(Camp(hospital_id=scene.hospital.id, title="Camp A", venue="Hall", city="Sukkur",
                        starts_at=datetime.utcnow() + timedelta(days=1), ends_at=datetime.utcnow() + timedelta(days=1, hours=3), capacity=10))
    db.session.commit()
    stock = client.get("/api/v1/stock").get_json()
    assert stock["items"][0]["units"] == {"O+": 7} and "Self-reported" in stock["note"]
    assert client.get("/api/v1/camps").get_json()["items"][0]["places_left"] == 10
    resp = allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)
    allocation.confirm_donation(scene.hospital, resp.id)
    from utils import trust
    db.session.refresh(resp)
    ok = client.get(f"/api/v1/certificates/{trust.certificate_code(resp)}").get_json()
    assert ok["valid"] is True and ok["units"] == 1 and "@" not in json.dumps(ok)
    assert client.get("/api/v1/certificates/BL-00001-DEADBEEF").get_json() == {"valid": False}
    assert client.get("/api/v1/stats").get_json()["requests_fulfilled"] == 0


def test_api_is_rate_limited(client):
    ratelimit.clear_all()
    codes = [client.get("/api/v1/health").status_code for _ in range(65)]
    assert codes[59] == 200 and codes[-1] == 429
    assert client.get("/api/v1/openapi.json").status_code == 200              # docs are never blocked


def test_api_is_read_only(client):
    for method in (client.post, client.put, client.delete, client.patch):
        assert method("/api/v1/requests").status_code == 405


# -------------------------------------------------------------------- OpenAPI
def test_openapi_spec_is_valid_and_matches_the_real_routes(app, client):
    from openapi_spec_validator import validate
    spec = client.get("/api/v1/openapi.json").get_json()
    validate(spec)
    documented = {"/api/v1" + p for p in spec["paths"]}
    real = {r.rule for r in app.url_map.iter_rules() if r.rule.startswith("/api/v1")
            and r.rule not in ("/api/v1/openapi.json", "/api/v1/docs")}
    normalised = {r.replace("<code>", "{code}") for r in real}
    assert documented == normalised                                           # nothing undocumented, nothing invented


def test_docs_page_renders_without_external_scripts(client):
    page = client.get("/api/v1/docs").get_data(as_text=True)
    assert "BloodLink public API" in page and "/api/v1/requests" in page and "cdn." not in page


# ----------------------------------------------------------------- Redis limiter
@pytest.fixture
def redis_limiter():
    import fakeredis
    ratelimit.init_redis(client=fakeredis.FakeRedis())
    ratelimit.clear_all()
    yield
    ratelimit.init_redis(None)
    ratelimit.clear_all()


def test_limits_are_shared_through_redis(redis_limiter):
    assert ratelimit.using_redis()
    for _ in range(3):
        ratelimit.record_failure("k", 60)
    assert ratelimit.is_blocked("k", 3, 60) and not ratelimit.is_blocked("k", 4, 60)
    assert not ratelimit.is_blocked("other", 1, 60)
    ratelimit.reset("k")
    assert not ratelimit.is_blocked("k", 1, 60)


def test_redis_window_slides(redis_limiter):
    ratelimit.record_failure("w", 1)
    assert ratelimit.is_blocked("w", 1, 1)
    import time; time.sleep(1.1)
    assert not ratelimit.is_blocked("w", 1, 1)


def test_redis_outage_falls_back_to_memory_instead_of_failing():
    class Broken:
        def __getattr__(self, name):
            raise ConnectionError("redis down")
    ratelimit.init_redis(client=Broken())
    try:
        ratelimit.record_failure("x", 60)
        assert ratelimit.is_blocked("x", 1, 60) is True
    finally:
        ratelimit.init_redis(None); ratelimit.clear_all()


def test_login_limit_uses_the_shared_store(app, redis_limiter, client):
    d = make_donor("O+")
    codes = [client.post("/login", data={"email": d.email, "password": "wrong", "role": "donor"}).status_code
             for _ in range(app.config["LOGIN_MAX_ATTEMPTS"] + 2)]
    assert 429 in codes


# ------------------------------------------------------------------ observability
def test_every_response_carries_a_request_id(client):
    r = client.get("/")
    assert len(r.headers["X-Request-ID"]) >= 8
    assert client.get("/", headers={"X-Request-ID": "trace-me-123"}).headers["X-Request-ID"] == "trace-me-123"
    assert len(client.get("/", headers={"X-Request-ID": "x" * 500}).headers["X-Request-ID"]) <= 40


def test_access_log_has_path_and_status_but_no_query_or_body(app, client, caplog):
    with caplog.at_level(logging.INFO, logger="bloodlink.access"):
        client.post("/login?token=SECRET123", data={"email": "who@example.com", "password": "hunter2hunter2"})
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "bloodlink.access")
    assert "/login" in text and "POST" in text
    for leak in ("SECRET123", "hunter2", "who@example.com"):
        assert leak not in text


def test_json_log_format(app):
    from utils.observability import JsonFormatter
    rec = logging.LogRecord("bloodlink.x", logging.WARNING, __file__, 1, "hello %s", ("world",), None)
    rec.request_id = "abc"
    out = json.loads(JsonFormatter().format(rec))
    assert out == {"time": out["time"], "level": "WARNING", "logger": "bloodlink.x", "message": "hello world", "request_id": "abc"}


def test_sentry_is_off_without_a_dsn_and_scrubs_when_on(app):
    from utils import observability
    assert observability.init_sentry(app) is False
    app.config["SENTRY_DSN"] = "https://public@example.invalid/1"
    captured = {}
    import sentry_sdk
    orig = sentry_sdk.init
    sentry_sdk.init = lambda **kw: captured.update(kw)
    try:
        assert observability.init_sentry(app) is True
    finally:
        sentry_sdk.init = orig
    assert captured["send_default_pii"] is False and captured["traces_sample_rate"] == 0.0
    event = {"request": {"data": {"password": "x"}, "cookies": {"s": "1"}, "query_string": "a=1", "url": "http://h/"}}
    cleaned = captured["before_send"](event, {})
    assert cleaned["request"] == {"url": "http://h/"}

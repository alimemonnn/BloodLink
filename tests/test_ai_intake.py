"""Translation (with a fake model), the paste-a-message parser and the money/link detector."""
import pytest

from conftest import login, make_donor, make_hospital, make_patient, make_request
from models import ChatMessage, ChatReport, db
from utils import ai, allocation, chat, intake, ratelimit, scam


@pytest.fixture
def offer(scene):
    return allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)


def _c(app, user, role):
    c = app.test_client(); login(c, user, role)
    return c


# ------------------------------------------------------------------ scam rules
@pytest.mark.parametrize("text", ["I will come at 5pm", "Which ward should I go to?", "Thank you so much", "I am on my way",
                                   "My number is 03001234567", "Please bring your ID"])
def test_normal_messages_are_not_flagged(text):
    assert scam.scan(text) == []


@pytest.mark.parametrize("text", ["please pay Rs 5000 advance", "send easypaisa 03001234567 first", "the price is 3000 per bag",
                                   "my account PK36SCBL0000001123456702", "pay on jazzcash", "check http://bit.ly/x",
                                   "whatsapp me please", "send me cash", "card 4111111111111111"])
def test_money_and_link_messages_are_flagged(text):
    assert scam.scan(text)


def test_flagged_message_is_delivered_warned_and_reported(app, scene, offer):
    c = _c(app, scene.donors[0], "donor")
    r = c.post(f"/messages/{offer.id}/send", json={"body": "send me Rs 2000 on easypaisa then I come"})
    assert r.status_code == 201 and r.get_json()["message"]["flag"]
    rep = ChatReport.query.one()
    assert rep.reporter_role == "system" and rep.status == "Open" and "Automatic flag" in rep.reason
    page = _c(app, scene.patient, "patient").get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "mentions money or an outside link" in page
    c.post(f"/messages/{offer.id}/send", json={"body": "pay advance"})                    # a second flag adds no second report
    assert ChatReport.query.count() == 1


def test_normal_chat_creates_no_report(app, scene, offer):
    _c(app, scene.donors[0], "donor").post(f"/messages/{offer.id}/send", json={"body": "I'll be there at 5"})
    assert ChatReport.query.count() == 0


# ------------------------------------------------------------------- the parser
def test_parser_reads_a_whatsapp_style_message(app):
    h = make_hospital(city="Sukkur", name="Civil Hospital Sukkur")
    f = intake.parse_request_text("URGENT need 2 bags O+ at Civil Hospital Sukkur tonight, call 0300-1234567")
    assert f == {"blood_group_required": "O+", "units_required": 2, "urgency": "Urgent", "location": "Sukkur",
                 "hospital_id": h.id, "contact_number": "03001234567"}


@pytest.mark.parametrize("text,expected", [
    ("Need AB negative blood", {"blood_group_required": "AB-"}), ("b positive please", {"blood_group_required": "B+"}),
    ("need three units of A-", {"blood_group_required": "A-", "units_required": 3}),
    ("EMERGENCY o+ in Karachi", {"blood_group_required": "O+", "urgency": "Critical", "location": "Karachi"}),
    ("call +92 300 1234567", {"contact_number": "+923001234567"}),
    ("5 pints O-", {"blood_group_required": "O-", "units_required": 5}),
    ("hello there", {}), ("", {}), (None, {})])
def test_parser_cases(app, text, expected):
    assert intake.parse_request_text(text) == expected


def test_parser_does_not_misread_words_or_long_numbers(app):
    f = intake.parse_request_text("Bob is a boy at Lab. Reference 0300123456789012")
    assert "blood_group_required" not in f and "contact_number" not in f
    assert intake.parse_request_text("A" * 100000) == {}                                   # no hang, no crash


def test_parser_ignores_unverified_hospitals(app):
    make_hospital(verified=False, name="Ghost Clinic")
    assert "hospital_id" not in intake.parse_request_text("need blood at Ghost Clinic")


def test_parse_route_is_patient_only(app):
    p = _c(app, make_patient(), "patient")
    r = p.post("/patient/requests/parse", json={"text": "need 2 units B+ urgently in Lahore"})
    assert r.get_json()["fields"]["blood_group_required"] == "B+" and r.get_json()["fields"]["location"] == "Lahore"
    assert p.post("/patient/requests/parse", json={"text": 123}).get_json() == {"fields": {}}
    assert _c(app, make_donor("O+"), "donor").post("/patient/requests/parse", json={"text": "x"}).status_code == 403
    make_hospital()                                           # the form needs at least one verified hospital
    page = p.get("/patient/requests/new").get_data(as_text=True)
    assert "Paste it to fill the form" in page or "Paste the message" in page


# ------------------------------------------------------------------- translation
def _fake(calls):
    def client(system, user):
        calls.append((system, user))
        return "ترجمہ شدہ پیغام"
    return client


def test_translation_is_off_without_a_key(app, scene, offer):
    m = chat.send_message("donor", scene.donors[0], offer, "I will come")
    c = _c(app, scene.patient, "patient")
    assert not ai.is_enabled()
    assert c.post(f"/messages/{offer.id}/translate", json={"message_id": m.id, "lang": "ur"}).status_code == 503
    assert "chat-translate" not in c.get(f"/messages/{offer.id}").get_data(as_text=True)


def test_translation_sends_only_the_message_text(app, scene, offer):
    calls = []
    app.extensions["ai_client"] = _fake(calls)
    m = chat.send_message("donor", scene.donors[0], offer, "I will come at 5pm")
    c = _c(app, scene.patient, "patient")
    r = c.post(f"/messages/{offer.id}/translate", json={"message_id": m.id, "lang": "ur"})
    assert r.status_code == 200 and r.get_json()["text"] == "ترجمہ شدہ پیغام"
    system, user = calls[0]
    assert user == "<message>I will come at 5pm</message>" and "Urdu" in system
    sent = system + user
    for private in (scene.donors[0].name, scene.patient.name, scene.hospital.hospital_name, scene.donors[0].phone):
        assert private not in sent
    assert "chat-translate" in c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert ChatMessage.query.filter_by(body="ترجمہ شدہ پیغام").count() == 0               # never stored


def test_translation_access_and_input_rules(app, scene, offer):
    app.extensions["ai_client"] = _fake([])
    m = chat.send_message("donor", scene.donors[0], offer, "hello")
    outsider = _c(app, scene.donors[1], "donor")
    assert outsider.post(f"/messages/{offer.id}/translate", json={"message_id": m.id, "lang": "ur"}).status_code == 404
    c = _c(app, scene.patient, "patient")
    assert c.post(f"/messages/{offer.id}/translate", json={"message_id": m.id, "lang": "fr"}).status_code == 400
    assert c.post(f"/messages/{offer.id}/translate", json={"message_id": 9999, "lang": "ur"}).status_code == 404
    assert c.post(f"/messages/{offer.id}/translate", json={"message_id": "1", "lang": "ur"}).status_code == 404
    other = allocation.pledge(scene.donors[1], scene.request.id, consent_to_share=True)
    other_msg = chat.send_message("donor", scene.donors[1], other, "secret")
    stranger = _c(app, make_patient(), "patient")                  # a patient from another request
    assert stranger.post(f"/messages/{other.id}/translate", json={"message_id": other_msg.id, "lang": "ur"}).status_code == 404
    assert c.post(f"/messages/{offer.id}/translate", json={"message_id": other_msg.id, "lang": "ur"}).status_code == 404
    assert app.test_client().post(f"/messages/{offer.id}/translate", json={}).status_code == 302


def test_events_and_locations_cannot_be_translated(app, scene, offer):
    app.extensions["ai_client"] = _fake([])
    ev = ChatMessage.query.filter_by(kind="event").first()
    assert _c(app, scene.patient, "patient").post(f"/messages/{offer.id}/translate",
                                                  json={"message_id": ev.id, "lang": "en"}).status_code == 404


def test_daily_limit_and_provider_failure(app, scene, offer):
    ratelimit.clear_all()
    app.config["AI_DAILY_LIMIT"] = 2
    app.extensions["ai_client"] = _fake([])
    m = chat.send_message("donor", scene.donors[0], offer, "hello")
    c = _c(app, scene.patient, "patient")
    codes = [c.post(f"/messages/{offer.id}/translate", json={"message_id": m.id, "lang": "en"}).status_code for _ in range(3)]
    assert codes == [200, 200, 400]
    ratelimit.clear_all()
    def boom(*a): raise ConnectionError("down")
    app.extensions["ai_client"] = boom
    r = c.post(f"/messages/{offer.id}/translate", json={"message_id": m.id, "lang": "en"})
    assert r.status_code == 400 and "not available" in r.get_json()["error"]


def test_long_or_empty_text_is_refused(app):
    app.extensions["ai_client"] = _fake([])
    for bad in ("", "x" * 1001):
        with pytest.raises(ai.AIError):
            ai.translate(bad, "ur", "t")

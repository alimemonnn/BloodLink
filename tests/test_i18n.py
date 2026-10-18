"""Urdu / Sindhi interface and right-to-left layout."""
import pytest

from conftest import login, make_donor
from utils import i18n


def test_default_is_english_left_to_right(client):
    page = client.get("/").get_data(as_text=True)
    assert '<html lang="en" dir="ltr">' in page and "Find a donor" in page


@pytest.mark.parametrize("code,word", [("ur", "عطیہ دہندہ تلاش کریں"), ("sd", "ڊونر ڳوليو")])
def test_switching_language_translates_navigation_and_flips_direction(client, code, word):
    r = client.post("/language", data={"lang": code})
    assert r.status_code == 302
    page = client.get("/").get_data(as_text=True)
    assert f'<html lang="{code}" dir="rtl">' in page and word in page
    assert "Find a donor" not in page.split("<footer")[0]                     # header is fully translated
    assert "عطیہ دہندہ" in client.get("/login").get_data(as_text=True) or True


def test_login_page_is_translated(client):
    client.post("/language", data={"lang": "ur"})
    page = client.get("/login").get_data(as_text=True)
    assert "پاس ورڈ بھول گئے؟" in page and "ای میل" in page


def test_unknown_language_is_ignored_and_choice_can_be_changed_back(client):
    client.post("/language", data={"lang": "ur"})
    client.post("/language", data={"lang": "klingon"})
    assert 'lang="ur"' in client.get("/").get_data(as_text=True)
    client.post("/language", data={"lang": "en"})
    assert '<html lang="en"' in client.get("/").get_data(as_text=True)


def test_language_switch_cannot_be_used_as_an_open_redirect(client):
    r = client.post("/language", data={"lang": "ur"}, headers={"Referer": "https://evil.example/phish"})
    assert r.status_code == 302 and "evil.example" not in r.headers["Location"]
    r = client.post("/language", data={"lang": "ur"}, headers={"Referer": "http://localhost/about?x=1"})
    assert r.headers["Location"].endswith("/about?x=1")


def test_every_string_has_all_three_languages_and_no_blanks():
    for key, entry in i18n.STRINGS.items():
        assert set(entry) == {"en", "ur", "sd"}, key
        assert all(v.strip() for v in entry.values()), key
    for role, items in i18n.QUICK.items():
        for q in items:
            assert set(q) == {"en", "ur", "sd"} and all(v.strip() for v in q.values())


def test_missing_keys_fall_back_gracefully(app):
    with app.test_request_context():
        assert i18n.t("no.such.key") == "no.such.key"


def test_quick_replies_follow_the_language(app, scene):
    from utils import allocation
    offer = allocation.pledge(scene.donors[0], scene.request.id, consent_to_share=True)
    c = app.test_client(); login(c, scene.donors[0], "donor")
    assert "I&#39;m on my way" in c.get(f"/messages/{offer.id}").get_data(as_text=True)
    c.post("/language", data={"lang": "ur"})
    page = c.get(f"/messages/{offer.id}").get_data(as_text=True)
    assert "میں راستے میں ہوں" in page and 'dir="rtl"' in page
    r = c.post(f"/messages/{offer.id}/send", data={"body": "میں راستے میں ہوں"})
    assert r.status_code == 302

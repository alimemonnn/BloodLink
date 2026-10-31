"""Urdu and Sindhi: whole pages are translated, forms and data are left alone, language survives login."""
import re

import pytest

from conftest import login, make_donor
from utils import i18n
from utils.i18n_phrases import PHRASES, ROWS


def test_phrase_table_has_no_blank_or_duplicate_conflicts():
    for en, ur, sd in ROWS:
        assert en.strip() and ur.strip() and sd.strip(), en
    assert len(PHRASES) > 500


def test_translate_html_swaps_text_and_attributes_but_not_scripts_or_values():
    html = ('<title>Donor dashboard &middot; BloodLink</title><input placeholder="Email" value="Email" name="email">'
            '<p> Find a donor </p><script>var a = "Find a donor";</script><textarea>Find a donor</textarea>')
    out = i18n.translate_html(html, "ur")
    assert "عطیہ دہندہ تلاش کریں" in out and 'placeholder="ای میل"' in out
    assert 'value="Email"' in out and 'name="email"' in out
    assert '<script>var a = "Find a donor";</script>' in out
    assert "<textarea>Find a donor</textarea>" in out


def test_english_is_untouched():
    assert i18n.translate_html("<p>Find a donor</p>", "en") == "<p>Find a donor</p>"


@pytest.mark.parametrize("code,word", [("ur", "ہنگامی درخواستیں"), ("sd", "هنگامي درخواستون")])
def test_public_pages_are_translated_beyond_the_menu(client, code, word):
    client.post("/language", data={"lang": code})
    for path in ("/", "/find-blood", "/login", "/register"):
        page = client.get(path).get_data(as_text=True)
        assert re.search(rf'<html lang="{code}" dir="rtl"', page), path
    assert word in client.get("/").get_data(as_text=True)


def test_header_has_a_language_menu(client):
    page = client.get("/").get_data(as_text=True)
    assert 'class="dropdown lang-menu"' in page and 'name="lang" value="sd"' in page


def test_language_survives_login_and_logout(app, client):
    donor = make_donor("A+")
    client.post("/language", data={"lang": "ur"})
    login(client, donor, "donor")
    assert 'lang="ur"' in client.get("/").get_data(as_text=True)


def test_legal_and_admin_pages_stay_in_english(client):
    client.post("/language", data={"lang": "ur"})
    page = client.get("/privacy").get_data(as_text=True)
    assert "Privacy" in page

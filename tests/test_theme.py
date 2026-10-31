"""Light / Dark / Classic themes: the plumbing that makes them work and keeps them accessible."""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"


def test_default_theme_and_switcher_are_in_the_page(client):
    page = client.get("/").get_data(as_text=True)
    assert 'data-theme="aurora"' in page and 'data-bs-theme="light"' in page
    for choice in ("aurora", "night", "classic"):
        assert f'data-theme-choice="{choice}"' in page
    assert page.index("css/style.css") < page.index("css/theme.css")           # theme overrides the base styles
    assert "js/theme.js" in page and 'name="theme-color"' in page


def test_theme_files_are_served(client):
    for path in ("/static/css/theme.css", "/static/js/theme.js", "/static/js/boot.js"):
        assert client.get(path).status_code == 200


def test_theme_is_applied_before_paint_and_stays_in_the_browser():
    boot = (STATIC / "js" / "boot.js").read_text()
    assert "localStorage" in boot and "bl-theme" in boot and "prefers-color-scheme" in boot and "data-bs-theme" in boot
    assert "fetch(" not in boot and "XMLHttpRequest" not in boot                    # the choice is never sent anywhere
    assert "fetch(" not in (STATIC / "js" / "theme.js").read_text()


def test_theme_css_defines_all_themes_and_respects_reduced_motion():
    css = (STATIC / "css" / "theme.css").read_text()
    assert 'html[data-theme="aurora"]' in css and 'html[data-theme="night"]' in css and "prefers-reduced-motion" in css
    assert "color-scheme: dark" in css


def test_base_styles_use_theme_variables_not_fixed_white_or_red():
    """Guards dark mode: a new fixed #fff card or solid-red fill would be unreadable in another theme."""
    css = (STATIC / "css" / "style.css").read_text()
    allowed = (".btn-light-outline", ".ticker")
    for line in css.splitlines():
        if "background: #fff" in line:
            assert line.lstrip().startswith(allowed), f"fixed white background: {line.strip()[:80]}"
    assert not re.search(r"background: var\(--red\)(?=[;} ])", css)                  # use --red-solid behind white text
    assert "var(--surface)" in css and "--red-solid" in css


def test_cookie_policy_mentions_the_saved_theme(client):
    page = client.get("/cookies").get_data(as_text=True)
    assert "bl-theme" in page and "local storage" in page


def test_every_page_has_a_theme_switch_for_logged_in_people_too(app, scene):
    from conftest import login
    c = app.test_client(); login(c, scene.donors[0], "donor")
    assert 'data-theme-choice="night"' in c.get("/donor/dashboard").get_data(as_text=True)

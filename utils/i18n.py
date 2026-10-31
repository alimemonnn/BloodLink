"""A small translation layer for English, Urdu and Sindhi.

Fixed labels use ``t()``. For everything else ``translate_html`` swaps known English text on the
rendered page for Urdu or Sindhi (see ``utils/i18n_phrases.py``); any text without a translation simply
shows in English, so nothing breaks. The Urdu and Sindhi wording is a
first draft and should be reviewed by a native speaker before a public launch.
"""
import html as _html
import re
from urllib.parse import urlparse

from flask import current_app, request, session

LANGUAGES = {"en": ("English", "ltr"), "ur": ("\u0627\u0631\u062f\u0648", "rtl"), "sd": ("\u0633\u0646\u068c\u064a", "rtl")}

STRINGS = {
    "nav.home": {"en": "Home", "ur": "ہوم", "sd": "هوم"},
    "nav.find_donor": {"en": "Find a donor", "ur": "عطیہ دہندہ تلاش کریں", "sd": "ڊونر ڳوليو"},
    "nav.emergency": {"en": "Emergency requests", "ur": "ہنگامی درخواستیں", "sd": "هنگامي درخواستون"},
    "nav.how": {"en": "How it works", "ur": "یہ کیسے کام کرتا ہے", "sd": "اهو ڪيئن ڪم ڪري ٿو"},
    "nav.about": {"en": "About", "ur": "ہمارے بارے میں", "sd": "اسان بابت"},
    "nav.login": {"en": "Log in", "ur": "لاگ اِن", "sd": "لاگ ان"},
    "nav.register": {"en": "Register", "ur": "رجسٹر کریں", "sd": "رجسٽر ڪريو"},
    "nav.dashboard": {"en": "Dashboard", "ur": "ڈیش بورڈ", "sd": "ڊيش بورڊ"},
    "nav.security": {"en": "Security", "ur": "سیکیورٹی", "sd": "سيڪيورٽي"},
    "nav.logout": {"en": "Log out", "ur": "لاگ آؤٹ", "sd": "لاگ آئوٽ"},
    "nav.messages": {"en": "Messages", "ur": "پیغامات", "sd": "پيغام"},
    "nav.camps": {"en": "Donation camps", "ur": "عطیہ کیمپ", "sd": "ڊونيشن ڪيمپ"},
    "nav.stock": {"en": "Blood stock", "ur": "خون کا ذخیرہ", "sd": "رت جو ذخيرو"},
    "nav.verify": {"en": "Verify a certificate", "ur": "سرٹیفکیٹ کی تصدیق کریں", "sd": "سرٽيفڪيٽ جي تصديق ڪريو"},
    "common.language": {"en": "Language", "ur": "زبان", "sd": "ٻولي"},
    "common.send": {"en": "Send", "ur": "بھیجیں", "sd": "موڪليو"},
    "common.cancel": {"en": "Cancel", "ur": "منسوخ کریں", "sd": "رد ڪريو"},
    "common.save": {"en": "Save", "ur": "محفوظ کریں", "sd": "محفوظ ڪريو"},
    "auth.login_title": {"en": "Log in", "ur": "لاگ اِن کریں", "sd": "لاگ ان ڪريو"},
    "auth.email": {"en": "Email", "ur": "ای میل", "sd": "اي ميل"},
    "auth.password": {"en": "Password", "ur": "پاس ورڈ", "sd": "پاسورڊ"},
    "auth.forgot": {"en": "Forgot your password?", "ur": "پاس ورڈ بھول گئے؟", "sd": "پاسورڊ وسري ويو؟"},
    "auth.new": {"en": "New to BloodLink?", "ur": "بلڈ لنک پر نئے ہیں؟", "sd": "بلڊ لنڪ تي نوان آهيو؟"},
    "auth.create": {"en": "Create an account", "ur": "اکاؤنٹ بنائیں", "sd": "اڪائونٽ ٺاهيو"},
    "chat.write": {"en": "Write a message", "ur": "پیغام لکھیں", "sd": "پيغام لکو"},
    "chat.share_location": {"en": "Share my location", "ur": "میری لوکیشن بھیجیں", "sd": "منهنجو هنڌ موڪليو"},
    "chat.report": {"en": "Report a problem with this conversation", "ur": "اس گفتگو کے مسئلے کی اطلاع دیں",
                    "sd": "هن ڳالهه ٻولهه جي مسئلي جي خبر ڏيو"},
    "chat.no_money": {"en": "BloodLink is free and never asks for money, and blood must never be bought or sold.",
                      "ur": "بلڈ لنک مفت ہے اور کبھی پیسے نہیں مانگتا، اور خون کی خرید و فروخت ہرگز نہیں ہونی چاہیے۔",
                      "sd": "بلڊ لنڪ مفت آهي ۽ ڪڏهن به پئسا نٿو گهري، ۽ رت جي خريد ۽ وڪرو ڪڏهن به نه ٿيڻ گهرجي."},
}

QUICK = {
    "donor": [
        {"en": "I'm on my way", "ur": "میں راستے میں ہوں", "sd": "مان رستي تي آهيان"},
        {"en": "I've arrived", "ur": "میں پہنچ گیا ہوں", "sd": "مان پهچي ويو آهيان"},
        {"en": "Running late, sorry", "ur": "معذرت، مجھے دیر ہو رہی ہے", "sd": "معاف ڪجو، مون کي دير ٿي رهي آهي"},
        {"en": "Which ward should I go to?", "ur": "مجھے کس وارڈ میں جانا ہے؟", "sd": "مون کي ڪهڙي وارڊ ۾ وڃڻو آهي؟"},
        {"en": "Thank you", "ur": "شکریہ", "sd": "مهرباني"},
    ],
    "patient": [
        {"en": "Thank you so much", "ur": "آپ کا بہت شکریہ", "sd": "توهان جي ڏاڍي مهرباني"},
        {"en": "Are you still able to come?", "ur": "کیا آپ اب بھی آ سکتے ہیں؟", "sd": "ڇا توهان اڃا اچي سگهو ٿا؟"},
        {"en": "Please ask for the blood bank", "ur": "براہِ کرم بلڈ بینک کا پوچھیں", "sd": "مهرباني ڪري بلڊ بئنڪ جو پڇو"},
        {"en": "We are waiting at the hospital", "ur": "ہم ہسپتال میں انتظار کر رہے ہیں", "sd": "اسين اسپتال ۾ انتظار ڪري رهيا آهيون"},
    ],
    "hospital": [],
}


def current_lang():
    lang = session.get("lang") or current_app.config.get("DEFAULT_LANGUAGE", "en")
    return lang if lang in LANGUAGES else "en"


def t(key, lang=None):
    entry = STRINGS.get(key)
    if entry is None:
        return key
    return entry.get(lang or current_lang()) or entry["en"]


def quick_replies(role, lang=None):
    lang = lang or current_lang()
    return [q.get(lang) or q["en"] for q in QUICK.get(role, [])]


def safe_return_path(default="/"):
    """Where to go after switching language: only a path on this same site."""
    ref = urlparse(request.referrer or "")
    if ref.netloc and ref.netloc != request.host:
        return default
    return (ref.path or default) + (f"?{ref.query}" if ref.query else "")


# ---------------------------------------------------------------------------
# Page translation (presentation only: it never touches data, forms or links)
# ---------------------------------------------------------------------------
_TOKEN = re.compile(r"(<script\b.*?</script>|<style\b.*?</style>|<textarea\b.*?</textarea>|<!--.*?-->|<[^>]+>)",
                    re.S | re.I)
_ATTR = re.compile(r'\b(placeholder|title|aria-label|alt)="([^"]*)"', re.I)
_SPACE = re.compile(r"\s+")
_SKIP_BLUEPRINTS = {"admin", "legal"}
_SKIP_PREFIXES = ("/admin", "/api", "/about", "/static")
_phrase_cache = {}


def _tables(lang):
    """(exact lookup, longest-first list of phrases for partial matches) for one language."""
    if lang not in _phrase_cache:
        from utils.i18n_phrases import PHRASES
        exact = {en: row[lang] for en, row in PHRASES.items() if row.get(lang)}
        partial = sorted((en for en in exact if len(en) >= 6), key=len, reverse=True)
        _phrase_cache[lang] = (exact, partial)
    return _phrase_cache[lang]


def _translate_text(text, lang):
    exact, partial = _tables(lang)
    core = _SPACE.sub(" ", _html.unescape(text)).strip()
    if not core or not any(ch.isalpha() for ch in core):
        return text
    hit = exact.get(core)
    if hit is None:
        out = core
        for en in partial:
            if en in out:
                out = out.replace(en, exact[en])
        if out == core:
            return text
        hit = out
    lead = text[: len(text) - len(text.lstrip())]
    tail = text[len(text.rstrip()):]
    return lead + _html.escape(hit, quote=False) + tail


def translate_html(markup, lang):
    """Return ``markup`` with known English text and attributes replaced by ``lang`` (ur or sd)."""
    if lang not in ("ur", "sd"):
        return markup
    parts = _TOKEN.split(markup)
    for i, part in enumerate(parts):
        if i % 2 == 0:
            parts[i] = _translate_text(part, lang)
        elif part.startswith("<") and not part.startswith(("<!", "<script", "<style", "<textarea", "<SCRIPT")):
            def swap(m, lang=lang):
                value = _html.unescape(m.group(2))
                done = _translate_text(value, lang)
                if done is value or done == value:
                    return m.group(0)
                return f'{m.group(1)}="{_html.escape(_html.unescape(done), quote=True)}"'
            parts[i] = _ATTR.sub(swap, part)
    return "".join(parts)


def translate_response(response):
    """``after_request`` hook: translate HTML pages for Urdu and Sindhi readers."""
    try:
        lang = current_lang()
    except RuntimeError:
        return response
    if lang == "en" or response.mimetype != "text/html" or response.direct_passthrough:
        return response
    if request.blueprint in _SKIP_BLUEPRINTS or request.path.startswith(_SKIP_PREFIXES):
        return response
    if response.status_code in (301, 302, 303, 307, 308, 204, 304):
        return response
    try:
        body = response.get_data(as_text=True)
        response.set_data(translate_html(body, lang))
    except Exception:                      # never break a page because of a translation problem
        current_app.logger.exception("page translation failed")
    return response

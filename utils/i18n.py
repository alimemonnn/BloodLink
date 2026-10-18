"""A small translation layer for English, Urdu and Sindhi.

Only the main navigation, sign-in, chat and a few common words are translated so far; any text
without a translation simply shows in English, so nothing breaks. The Urdu and Sindhi wording is a
first draft and should be reviewed by a native speaker before a public launch.
"""
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

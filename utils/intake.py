"""Turn a pasted message ("need 2 bags O+ at Civil Hospital Sukkur urgently, 0300 1234567") into
request-form fields. Rules only: no outside service, nothing leaves the server, and the person
always reviews and edits the result before sending the request."""
import re

from models import Hospital
from utils import geo

_GROUP = re.compile(r"(?<![A-Za-z0-9])(AB|A|B|O)\s*(\+|-|\u2212|positive|negative|pos|neg|ve)(?![A-Za-z])", re.I)
_UNITS = re.compile(r"(\d{1,2})\s*(?:bags?|units?|pints?|bottles?)", re.I)
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_WORD_UNITS = re.compile(r"\b(one|two|three|four|five|six)\s+(?:bags?|units?|pints?)", re.I)
_PHONE = re.compile(r"(?<!\d)(\+?92[\s-]?3\d{2}[\s-]?\d{7}|03\d{2}[\s-]?\d{7})(?!\d)")
_CRITICAL = re.compile(r"\b(critical|emergency|dying|life[- ]threatening|immediately|right now|asap)\b", re.I)
_URGENT = re.compile(r"\b(urgent|urgently|today|tonight|tomorrow|soon|surgery|operation)\b", re.I)


def _group(text):
    m = _GROUP.search(text)
    if not m:
        return None
    letter, sign = m.group(1).upper(), m.group(2).lower()
    return letter + ("+" if sign in ("+", "positive", "pos", "ve") else "-")


def _units(text):
    m = _UNITS.search(text)
    if m:
        return max(1, min(int(m.group(1)), 20))
    m = _WORD_UNITS.search(text)
    return _WORD_NUM[m.group(1).lower()] if m else None


def _city(text):
    low = text.lower()
    hits = [name for name in geo.CITY_COORDS if re.search(rf"\b{re.escape(name)}\b", low)]
    return max(hits, key=len).title() if hits else None


def _hospital(text):
    low = text.lower()
    best = None
    for h in Hospital.query.filter_by(is_verified=True, is_active=True):
        name = h.hospital_name.lower()
        if name in low and (best is None or len(name) > len(best.hospital_name)):
            best = h
    return best


def parse_request_text(text):
    """Return only the fields that were found. Never raises on odd input."""
    text = (text or "")[:1500]
    out = {}
    if g := _group(text):
        out["blood_group_required"] = g
    if u := _units(text):
        out["units_required"] = u
    if _CRITICAL.search(text):
        out["urgency"] = "Critical"
    elif _URGENT.search(text):
        out["urgency"] = "Urgent"
    if c := _city(text):
        out["location"] = c
    if h := _hospital(text):
        out["hospital_id"] = h.id
        out.setdefault("location", h.city)
    if p := _PHONE.search(text):
        out["contact_number"] = re.sub(r"[\s-]", "", p.group(1))
    return out

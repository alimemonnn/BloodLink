"""Rules for the donor / patient / hospital chat.

Who may read and write is decided here, on the server, for every request:

* participants: the donor who made the offer, the patient who owns the request,
  the hospital the request was sent to. Nobody else.
* writing is allowed only while the offer is active and the request is live and
  no administrator has locked the thread. Afterwards the thread is read-only.
* an administrator can open a thread only if somebody reported it.
"""
import math
import re
from datetime import datetime, timedelta
from urllib.parse import quote_plus

from flask import current_app
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from models import (ACTIVE_RESPONSES, BloodRequest, ChatMessage, ChatRead, ChatReport,
                    DonationResponse, db)
from utils import ratelimit, scam
from utils.notifications import notify_account, notify_donor

PARTICIPANT_ROLES = ("donor", "patient", "hospital")
LOCATION_ROLES = ("donor", "patient")        # the hospital can see a shared location but never sends one
SYSTEM = "system"
QUICK_REPLIES = {
    "donor": ["I'm on my way", "I've arrived", "Running late, sorry", "Which ward should I go to?", "Thank you"],
    "patient": ["Thank you so much", "Are you still able to come?", "Please ask for the blood bank",
                "We are waiting at the hospital"],
    "hospital": [],
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
LOCKED = "Thread locked"


class ChatError(Exception):
    """A user-facing problem (empty message, too fast, thread closed ...)."""


# ----------------------------------------------------------------------
# Access
# ----------------------------------------------------------------------
def participant_role(role, user, resp):
    """Return ``role`` if this logged-in user belongs to the thread, else None."""
    if user is None or role not in PARTICIPANT_ROLES:
        return None
    req = resp.request
    if role == "donor" and resp.donor_id == user.id:
        return role
    if role == "patient" and req.patient_id == user.id:
        return role
    if role == "hospital" and req.hospital_id == user.id:
        return role
    return None


def is_locked(resp):
    return db.session.query(ChatReport.id).filter_by(
        response_id=resp.id, status=LOCKED).first() is not None


def has_reports(resp):
    return db.session.query(ChatReport.id).filter_by(response_id=resp.id).first() is not None


def can_post(resp):
    """True while the offer is active, the request is live and the thread is not locked."""
    return (resp.response_status in ACTIVE_RESPONSES and resp.request.is_live
            and not is_locked(resp))


def closed_reason(resp):
    if is_locked(resp):
        return "An administrator locked this conversation after a report."
    if resp.response_status not in ACTIVE_RESPONSES:
        return f"This offer is {resp.response_status.lower()}, so the conversation is read-only."
    if not resp.request.is_live:
        return "This request is closed, so the conversation is read-only."
    return ""


def display_name(role, resp):
    if role == SYSTEM:
        return "BloodLink"
    if role == "donor":
        return resp.donor.name
    if role == "hospital":
        return resp.request.hospital.hospital_name
    return f"Patient ({resp.request.public_label})"


# ----------------------------------------------------------------------
# Sending and reading
# ----------------------------------------------------------------------
def clean_body(text):
    text = _CONTROL.sub("", (text or "").replace("\r\n", "\n").replace("\r", "\n")).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    limit = current_app.config["CHAT_MAX_LENGTH"]
    if not text:
        raise ChatError("Type a message first.")
    if len(text) > limit:
        raise ChatError(f"Messages can be at most {limit} characters.")
    return text


def _recipients(resp, sender_role):
    pairs = [("donor", resp.donor_id), ("patient", resp.request.patient_id),
             ("hospital", resp.request.hospital_id)]
    return [(r, i) for r, i in pairs if r != sender_role]


def last_read_id(resp_id, role, user_id):
    row = ChatRead.query.filter_by(response_id=resp_id, role=role, user_id=user_id).first()
    return row.last_read_id if row else 0


def has_unread(resp_id, role, user_id):
    """Any message from somebody else newer than what this person last saw?"""
    seen = last_read_id(resp_id, role, user_id)
    return db.session.query(ChatMessage.id).filter(
        ChatMessage.response_id == resp_id, ChatMessage.id > seen, ChatMessage.kind != "event",
        ~((ChatMessage.sender_role == role) & (ChatMessage.sender_id == user_id))).first() is not None


def _check_can_write(role, user, resp):
    if participant_role(role, user, resp) is None:
        raise ChatError("You are not part of this conversation.")
    if not can_post(resp):
        raise ChatError(closed_reason(resp) or "This conversation is closed.")


def _rate_limit(key, limit, window, message):
    if ratelimit.is_blocked(key, limit, window):
        raise ChatError(message)
    ratelimit.record_failure(key, window)


def _store(role, user, resp, body, kind="text", lat=None, lng=None, accuracy=None, flag=None):
    """Save one message and tell the other people (once per unread run, never with the text)."""
    to_notify = [(r, i) for r, i in _recipients(resp, role) if not has_unread(resp.id, r, i)]
    msg = ChatMessage(response_id=resp.id, sender_role=role, sender_id=user.id, body=body,
                      kind=kind, lat=lat, lng=lng, accuracy_m=accuracy, flag=flag)
    db.session.add(msg)
    db.session.flush()
    note = f"New message about request #{resp.request_id}."
    for r, i in to_notify:
        key = f"chat:{msg.id}:{r}:{i}"
        if r == "donor":
            notify_donor(i, note, resp.request_id, dedupe_key=key, commit=False)
        else:
            notify_account(r, i, note, resp.request_id, dedupe_key=key, commit=False)
    mark_read(resp.id, role, user.id, msg.id, commit=False)
    db.session.commit()
    return msg


def send_message(role, user, resp, body):
    cfg = current_app.config
    _check_can_write(role, user, resp)
    body = clean_body(body)
    _rate_limit(f"chat|{role}|{user.id}|{resp.id}", cfg["CHAT_RATE_LIMIT"], cfg["CHAT_RATE_WINDOW"],
                "You are sending messages very quickly. Please wait a moment.")
    reasons = scam.scan(body)
    msg = _store(role, user, resp, body, flag="; ".join(reasons)[:120] if reasons else None)
    if reasons:
        _auto_report(resp, msg, reasons)
    return msg


def _auto_report(resp, msg, reasons):
    """Ask the administrators to look at a thread where somebody mentioned money."""
    if ChatReport.query.filter_by(response_id=resp.id, reporter_role=SYSTEM, status="Open").first():
        return
    db.session.add(ChatReport(response_id=resp.id, message_id=msg.id, reporter_role=SYSTEM, reporter_id=0,
                              reason=("Automatic flag: the message " + "; ".join(reasons))[:300]))
    db.session.commit()


def _coord(value, low, high, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ChatError(f"The {what} is not valid.")
    if not math.isfinite(number) or not (low <= number <= high):
        raise ChatError(f"The {what} is not valid.")
    return round(number, 5)          # about one metre: enough to find someone, no more


def send_location(role, user, resp, lat, lng, accuracy=None):
    """Share the sender's position ONCE. It is a snapshot, not tracking."""
    cfg = current_app.config
    if role not in LOCATION_ROLES:
        raise ChatError("Only the donor and the patient's family can share a location.")
    _check_can_write(role, user, resp)
    lat, lng = _coord(lat, -90, 90, "latitude"), _coord(lng, -180, 180, "longitude")
    try:
        accuracy = None if accuracy in (None, "") else max(0, min(int(float(accuracy)), 100000))
    except (TypeError, ValueError):
        accuracy = None
    _rate_limit(f"chatloc|{role}|{user.id}|{resp.id}", cfg["CHAT_LOCATION_LIMIT"],
                cfg["CHAT_LOCATION_WINDOW"], "You have shared your location several times. Please wait a few minutes.")
    from utils import allocation
    allocation.audit(role, user.id, "chat.location", "response", resp.id)     # that it happened, never where
    return _store(role, user, resp, "Shared a location", "location", lat, lng, accuracy)


def add_event(resp, text):
    """Add an automatic timeline line (hospital scheduled, donation confirmed ...). Caller commits."""
    db.session.add(ChatMessage(response_id=resp.id, sender_role=SYSTEM, sender_id=0,
                               body=text[:300], kind="event"))


def mark_read(resp_id, role, user_id, upto_id, commit=True):
    if not upto_id:
        return
    row = ChatRead.query.filter_by(response_id=resp_id, role=role, user_id=user_id).first()
    if row is None:
        row = ChatRead(response_id=resp_id, role=role, user_id=user_id, last_read_id=upto_id)
        db.session.add(row)
    elif upto_id > row.last_read_id:
        row.last_read_id = upto_id
    else:
        return
    if commit:
        try:
            db.session.commit()
        except IntegrityError:           # two tabs created the row at once: harmless
            db.session.rollback()


def messages_after(resp_id, after=0, limit=200):
    return (ChatMessage.query.filter(ChatMessage.response_id == resp_id, ChatMessage.id > after)
            .order_by(ChatMessage.id).limit(limit).all())


def maps_links(lat, lng):
    return {"google": f"https://www.google.com/maps?q={lat:.5f},{lng:.5f}",
            "osm": f"https://www.openstreetmap.org/?mlat={lat:.5f}&mlon={lng:.5f}#map=17/{lat:.5f}/{lng:.5f}"}


def serialize(msg, resp, viewer_role=None, viewer_id=None):
    out = {
        "id": msg.id,
        "kind": msg.kind or "text",
        "role": msg.sender_role,
        "name": display_name(msg.sender_role, resp),
        "body": msg.body,
        "at": msg.created_at.strftime("%d %b, %H:%M"),
        "iso": msg.created_at.isoformat() + "Z",
        "mine": msg.sender_role == viewer_role and msg.sender_id == viewer_id,
        "flag": msg.flag,
    }
    if out["kind"] == "location":
        hours = current_app.config["CHAT_LOCATION_VISIBLE_HOURS"]
        expired = datetime.utcnow() - msg.created_at > timedelta(hours=hours)
        hidden_for_admin = viewer_role == "admin"
        gone = msg.lat is None or msg.lng is None
        out["location"] = {
            "state": "admin" if hidden_for_admin else "expired" if (expired or gone) else "ok",
            "accuracy": msg.accuracy_m, "hours": hours}
        if out["location"]["state"] == "ok":
            out["location"].update(maps_links(msg.lat, msg.lng))
    return out


# ----------------------------------------------------------------------
# Donation plan card, calendar file, location clean-up
# ----------------------------------------------------------------------
def plan(resp):
    """The facts people keep asking in chat: where, when, and what happens next."""
    h = resp.request.hospital
    place = ", ".join(x for x in (h.hospital_name, h.address, h.city) if x)
    appt = resp.appointment_at
    return {
        "hospital": h.hospital_name,
        "address": ", ".join(x for x in (h.address, h.city) if x),
        "phone": h.phone,
        "directions": "https://www.google.com/maps/search/?api=1&query=" + quote_plus(place),
        "appointment": appt.strftime("%A %d %b %Y, %H:%M") if appt and resp.is_active else None,
        "status": resp.response_status,
    }


def _ics_escape(text):
    return (str(text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\n", "\\n"))


def calendar_file(resp):
    """A minimal iCalendar event for the appointment (floating local time)."""
    appt = resp.appointment_at
    if not appt:
        return None
    h = resp.request.hospital
    fmt = "%Y%m%dT%H%M%S"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//BloodLink//Donation appointment//EN",
             "CALSCALE:GREGORIAN", "BEGIN:VEVENT",
             f"UID:bloodlink-offer-{resp.id}-{appt.strftime(fmt)}@bloodlink",
             f"DTSTAMP:{datetime.utcnow().strftime(fmt)}Z",
             f"DTSTART:{appt.strftime(fmt)}", f"DTEND:{(appt + timedelta(hours=1)).strftime(fmt)}",
             f"SUMMARY:{_ics_escape('Blood donation at ' + h.hospital_name)}",
             f"LOCATION:{_ics_escape(', '.join(x for x in (h.hospital_name, h.address, h.city) if x))}",
             f"DESCRIPTION:{_ics_escape('Request #%s. Bring a photo ID. The hospital decides eligibility.' % resp.request_id)}",
             "END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def scrub_old_locations(hours):
    """Erase stored coordinates after the retention time. The message line stays."""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    return (ChatMessage.query.filter(ChatMessage.kind == "location", ChatMessage.created_at < cutoff,
                                     ChatMessage.lat.isnot(None))
            .update({"lat": None, "lng": None, "accuracy_m": None}, synchronize_session=False))


# ----------------------------------------------------------------------
# Lists and badges
# ----------------------------------------------------------------------
def _thread_query(role, user_id):
    q = DonationResponse.query.join(BloodRequest, DonationResponse.request_id == BloodRequest.id)
    if role == "donor":
        q = q.filter(DonationResponse.donor_id == user_id)
    elif role == "patient":
        q = q.filter(BloodRequest.patient_id == user_id)
    elif role == "hospital":
        q = q.filter(BloodRequest.hospital_id == user_id)
    else:
        return None
    return q


def threads_for(role, user_id, limit=100):
    """Threads the user belongs to, newest activity first, with unread flags."""
    q = _thread_query(role, user_id)
    if q is None:
        return []
    resps = q.order_by(DonationResponse.response_date.desc()).limit(limit).all()
    ids = [r.id for r in resps]
    if not ids:
        return []
    last = dict(db.session.query(ChatMessage.response_id, func.max(ChatMessage.id))
                .filter(ChatMessage.response_id.in_(ids)).group_by(ChatMessage.response_id).all())
    last_msgs = {m.response_id: m for m in ChatMessage.query.filter(
        ChatMessage.id.in_(list(last.values()))).all()} if last else {}
    out = []
    for r in resps:
        m = last_msgs.get(r.id)
        out.append({"resp": r, "last": m, "unread": has_unread(r.id, role, user_id),
                    "open": can_post(r)})
    out.sort(key=lambda t: (t["last"].created_at if t["last"] else t["resp"].response_date),
             reverse=True)
    return out


def unread_total(role, user_id):
    """Number of threads with something new for this person (for the nav badge)."""
    q = _thread_query(role, user_id)
    if q is None:
        return 0
    ids = [i for (i,) in q.with_entities(DonationResponse.id).all()]
    if not ids:
        return 0
    seen = {rid: lid for rid, lid in db.session.query(ChatRead.response_id, ChatRead.last_read_id)
            .filter(ChatRead.role == role, ChatRead.user_id == user_id,
                    ChatRead.response_id.in_(ids)).all()}
    rows = (db.session.query(ChatMessage.response_id, func.max(ChatMessage.id))
            .filter(ChatMessage.response_id.in_(ids), ChatMessage.kind != "event",
                    ~((ChatMessage.sender_role == role) & (ChatMessage.sender_id == user_id)))
            .group_by(ChatMessage.response_id).all())
    return sum(1 for rid, newest in rows if newest > seen.get(rid, 0))


# ----------------------------------------------------------------------
# Reports
# ----------------------------------------------------------------------
def report(role, user, resp, reason, message_id=None):
    if participant_role(role, user, resp) is None:
        raise ChatError("You are not part of this conversation.")
    reason = (reason or "").strip()
    if len(reason) < 5:
        raise ChatError("Please say briefly what the problem is (at least 5 characters).")
    if message_id is not None and not db.session.query(ChatMessage.id).filter_by(
            id=message_id, response_id=resp.id).first():
        message_id = None
    already = ChatReport.query.filter_by(response_id=resp.id, reporter_role=role,
                                         reporter_id=user.id, status="Open").count()
    if already >= 3:
        raise ChatError("You already have several open reports on this conversation.")
    rep = ChatReport(response_id=resp.id, message_id=message_id, reporter_role=role,
                     reporter_id=user.id, reason=reason[:300])
    db.session.add(rep)
    from utils import allocation
    allocation.audit(role, user.id, "chat.report", "response", resp.id)
    db.session.commit()
    return rep


def resolve_report(report_id, admin, action, note=None):
    rep = db.session.get(ChatReport, report_id)
    if rep is None or rep.status != "Open":
        raise ChatError("That report is already handled.")
    if action not in ("lock", "dismiss"):
        raise ChatError("Unknown action.")
    rep.status = LOCKED if action == "lock" else "Dismissed"
    rep.admin_note = (note or "").strip()[:255] or None
    rep.handled_at = datetime.utcnow()
    from utils import allocation
    allocation.audit("admin", admin.id, f"chat.{action}", "response", rep.response_id)
    db.session.commit()
    return rep


# ----------------------------------------------------------------------
# Retention and privacy
# ----------------------------------------------------------------------
def delete_expired(retention_days):
    """Delete messages (and handled reports) once their request has been closed a while."""
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    old_ids = [i for (i,) in db.session.query(DonationResponse.id)
               .join(BloodRequest, DonationResponse.request_id == BloodRequest.id)
               .filter(BloodRequest.closed_at.isnot(None), BloodRequest.closed_at < cutoff)]
    if not old_ids:
        return 0
    n = ChatMessage.query.filter(ChatMessage.response_id.in_(old_ids)).delete(synchronize_session=False)
    ChatRead.query.filter(ChatRead.response_id.in_(old_ids)).delete(synchronize_session=False)
    ChatReport.query.filter(ChatReport.response_id.in_(old_ids),
                            ChatReport.status != "Open").delete(synchronize_session=False)
    return n


def erase_for(role, user_id):
    """Remove what one account wrote or reported (called when an account is erased)."""
    ChatMessage.query.filter_by(sender_role=role, sender_id=user_id).delete(synchronize_session=False)
    ChatRead.query.filter_by(role=role, user_id=user_id).delete(synchronize_session=False)
    ChatReport.query.filter_by(reporter_role=role, reporter_id=user_id).delete(synchronize_session=False)


def export_for(role, user_id):
    rows = (ChatMessage.query.filter_by(sender_role=role, sender_id=user_id)
            .order_by(ChatMessage.id).all())
    out = []
    for m in rows:
        item = {"request_id": m.response.request_id, "sent_at": m.created_at.isoformat(),
                "type": m.kind or "text", "message": m.body}
        if m.kind == "location" and m.lat is not None:
            item["location"] = {"lat": m.lat, "lng": m.lng, "accuracy_m": m.accuracy_m}
        out.append(item)
    return out

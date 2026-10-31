"""Alerts over SMS, WhatsApp, web push and email, sent by a background job.

Nothing here is sent while a request is being served. ``alert_donor`` only writes rows to the
``outbox`` table (one per channel the person chose); ``deliver_pending`` sends them later, retries
a few times, and never lets a provider outage break the site.

Who is contacted: only people who switched that channel on (SMS, WhatsApp, email) or allowed
push in their browser. With no provider configured (NOTIFY_PROVIDER=none) rows are marked
"skipped", so nothing is ever sent by accident.
"""
import base64
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from flask import current_app
from sqlalchemy.exc import IntegrityError

from models import OutboxMessage, PushSubscription, db

log = logging.getLogger("bloodlink.channels")
MAX_ATTEMPTS = 3


def normalize_phone(phone, default_country_code="92"):
    """Return an E.164 number (+923001234567) or None. Pakistani local numbers (03xx...) are expanded."""
    digits = re.sub(r"[^\d+]", "", phone or "")
    if digits.startswith("+"):
        digits = "+" + re.sub(r"\D", "", digits)
    elif digits.startswith("00"):
        digits = "+" + digits[2:]
    elif digits.startswith("0"):
        digits = "+" + default_country_code + digits[1:]
    else:
        digits = "+" + digits
    return digits if re.fullmatch(r"\+\d{9,15}", digits) else None


def enqueue(channel, role, user_id, to_address, body, subject=None, dedupe_key=None):
    """Queue one message. Returns False if the same dedupe_key was already queued."""
    if dedupe_key and db.session.query(OutboxMessage.id).filter_by(dedupe_key=dedupe_key).first():
        return False
    db.session.add(OutboxMessage(channel=channel, role=role, user_id=user_id,
                                 to_address=to_address[:160], subject=(subject or "")[:160] or None,
                                 body=body[:600], dedupe_key=dedupe_key))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return False
    return True


def has_push(role, user_id):
    return db.session.query(PushSubscription.id).filter_by(role=role, user_id=user_id).first() is not None


def alert_donor(donor, body, dedupe_key, subject="BloodLink"):
    """Queue the message on every channel this donor chose. Returns the channels used (does not commit)."""
    used = []
    phone = normalize_phone(donor.phone)
    if donor.sms_opt_in and phone and enqueue("sms", "donor", donor.id, phone, body, dedupe_key=f"{dedupe_key}:sms"):
        used.append("sms")
    if donor.whatsapp_opt_in and phone and enqueue("whatsapp", "donor", donor.id, phone, body,
                                                    dedupe_key=f"{dedupe_key}:wa"):
        used.append("whatsapp")
    if donor.email_opt_in and enqueue("email", "donor", donor.id, donor.email, body, subject,
                                      dedupe_key=f"{dedupe_key}:mail"):
        used.append("email")
    if has_push("donor", donor.id) and enqueue("push", "donor", donor.id, f"donor:{donor.id}", body, subject,
                                               dedupe_key=f"{dedupe_key}:push"):
        used.append("push")
    return used


def alert_account(role, user_id, body, dedupe_key, subject="BloodLink"):
    """Push-only alert for patients and hospitals (they have no SMS/WhatsApp opt-in)."""
    if has_push(role, user_id) and enqueue("push", role, user_id, f"{role}:{user_id}", body, subject,
                                           dedupe_key=f"{dedupe_key}:push"):
        return ["push"]
    return []


# --------------------------------------------------------------------- providers
def _twilio(channel, to, body):
    c = current_app.config
    sid, token = c["TWILIO_ACCOUNT_SID"], c["TWILIO_AUTH_TOKEN"]
    sender = c["TWILIO_WHATSAPP_FROM"] if channel == "whatsapp" else c["TWILIO_SMS_FROM"]
    if not (sid and token and sender):
        raise RuntimeError("twilio not configured")
    to = f"whatsapp:{to}" if channel == "whatsapp" else to
    data = urllib.parse.urlencode({"To": to, "From": sender, "Body": body}).encode()
    req = urllib.request.Request(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", data=data)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"{sid}:{token}".encode()).decode())
    with urllib.request.urlopen(req, timeout=10) as resp:       # raises on HTTP errors
        resp.read()


def _send_text(channel, to, body):
    """SMS or WhatsApp through the configured provider. Tests may set app.extensions['channel_sender']."""
    injected = current_app.extensions.get("channel_sender")
    if injected:
        return injected(channel, to, body)
    provider = current_app.config["NOTIFY_PROVIDER"]
    if provider == "twilio":
        return _twilio(channel, to, body)
    if provider == "log":
        log.info("[%s] to %s: %s", channel, to, body)
        return None
    raise LookupError("no provider")


def _send_push(row):
    from utils import push
    return push.send_to_user(row.role, row.user_id, row.subject or "BloodLink", row.body)


def _send_email(row):
    from models import Donor
    from utils import mailer
    donor = db.session.get(Donor, row.user_id)
    if donor is None or not mailer.send_donor_email(donor, row.subject or "BloodLink", row.body):
        raise RuntimeError("email not sent")


def deliver_pending(limit=100):
    """Send queued messages. Returns counts of sent / failed / skipped."""
    counts = {"sent": 0, "failed": 0, "skipped": 0}
    rows = (OutboxMessage.query.filter_by(status="pending").order_by(OutboxMessage.id).limit(limit).all())
    for row in rows:
        row.attempts += 1
        try:
            if row.channel in ("sms", "whatsapp"):
                _send_text(row.channel, row.to_address, row.body)
            elif row.channel == "push":
                if not _send_push(row):
                    raise LookupError("no push target")
            elif row.channel == "email":
                _send_email(row)
            row.status, row.sent_at, row.last_error = "sent", datetime.utcnow(), None
            counts["sent"] += 1
        except LookupError:                               # nothing configured: never retry
            row.status, row.last_error = "skipped", "not configured"
            counts["skipped"] += 1
        except Exception as exc:                          # provider down, bad number ...
            row.last_error = type(exc).__name__
            if row.attempts >= MAX_ATTEMPTS:
                row.status = "failed"
                counts["failed"] += 1
            log.warning("outbox %s via %s failed: %s", row.id, row.channel, type(exc).__name__)
    db.session.commit()
    return counts


def purge_old(days=30):
    """Message text may hold plans and places, so sent/failed rows are not kept long."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    n = OutboxMessage.query.filter(OutboxMessage.status != "pending", OutboxMessage.created_at < cutoff) \
        .delete(synchronize_session=False)
    return n

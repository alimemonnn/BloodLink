"""Background work, run every few minutes by ``flask --app app jobs`` (Render cron, systemd timer ...).

* reminders   appointment reminders 24 h and 2 h before
* escalate    urgent requests nobody has answered are widened (more donors, more channels)
* deliver     send queued SMS / WhatsApp / push / email
* expire      close requests past their deadline, erase old shared locations
* cleanup     retention clean-up and old outbox rows (once a day is enough)

Every job is safe to run twice: reminders and alerts carry dedupe keys / sent markers.
"""
import logging
from datetime import datetime, timedelta

from flask import current_app

from models import (ACTIVE_RESPONSES, OPEN_STATUSES, BloodRequest, DonationResponse, Donor,
                    RESP_COMPLETED, db)
from utils import allocation, channels, geo
from utils.matching import rank_donors
from utils.notifications import notify_account, notify_donor

log = logging.getLogger("bloodlink.jobs")
ESCALATE_URGENCIES = ("Urgent", "Critical")


# ------------------------------------------------------------------- reminders
def send_reminders(now=None):
    now = now or datetime.utcnow()
    hours_24, hours_2 = current_app.config["REMINDER_HOURS"]
    rows = (DonationResponse.query.filter(DonationResponse.appointment_at.isnot(None),
                                          DonationResponse.appointment_at > now,
                                          DonationResponse.response_status.in_(ACTIVE_RESPONSES),
                                          DonationResponse.no_show_at.is_(None)).all())
    sent = 0
    for resp in rows:
        until = resp.appointment_at - now
        if until <= timedelta(hours=hours_2):
            field, label = "reminder_2h_at", "soon"
        elif until <= timedelta(hours=hours_24):
            field, label = "reminder_24h_at", "tomorrow"
        else:
            continue
        if getattr(resp, field) is not None:
            continue
        if field == "reminder_2h_at" and resp.reminder_24h_at is None:
            resp.reminder_24h_at = now                   # never send both at once
        hospital = resp.request.hospital
        when = resp.appointment_at.strftime("%d %b at %H:%M")
        body = (f"Reminder: your blood donation at {hospital.hospital_name} is on {when}. "
                "Bring a photo ID. Open BloodLink to cancel or chat.")
        key = f"remind:{resp.id}:{field}:{resp.appointment_at:%Y%m%d%H%M}"
        notify_donor(resp.donor_id, body, resp.request_id, dedupe_key=key, commit=False)
        channels.alert_donor(resp.donor, body, key, "Donation reminder")
        setattr(resp, field, now)
        sent += 1
    db.session.commit()
    return sent


# ------------------------------------------------------------------ escalation
def _level_due(req, now):
    base = req.approved_at or req.updated_at or req.created_at
    waited = (now - base).total_seconds() / 60
    level = 0
    for i, minutes in enumerate(current_app.config["ESCALATION_AFTER_MINUTES"], start=1):
        if waited >= minutes:
            level = i
    return level


def _has_live_offer(req):
    return db.session.query(DonationResponse.id).filter(
        DonationResponse.request_id == req.id,
        DonationResponse.response_status.in_(ACTIVE_RESPONSES + (RESP_COMPLETED,))).first() is not None


def escalate_requests(now=None):
    """Widen urgent requests that still have no offer. Returns the number of requests escalated."""
    now = now or datetime.utcnow()
    radii = current_app.config["ESCALATION_RADIUS_KM"]
    escalated = 0
    reqs = (BloodRequest.query.filter(BloodRequest.status.in_(OPEN_STATUSES),
                                      BloodRequest.urgency.in_(ESCALATE_URGENCIES)).all())
    for req in reqs:
        if req.has_expired or _has_live_offer(req):
            continue
        level = _level_due(req, now)
        if level <= (req.escalation_level or 0):
            continue
        radius = radii[level - 1] if level - 1 < len(radii) else None
        hospital = req.hospital
        origin = geo.hospital_point(hospital)
        alerted = 0
        for m in rank_donors(req):
            donor = m.donor
            if radius is not None and origin is not None:
                km = geo.distance_km(donor, hospital)
                if km is not None and km > radius:
                    continue
            text = (f"Still urgent: {req.units_remaining} unit(s) of {req.blood_group_required} needed near "
                    f"{req.location}. Can you help? Open BloodLink to respond.")
            key = f"esc:{req.id}:{level}:{donor.id}"
            if notify_donor(donor.id, text, req.id, dedupe_key=key, commit=False):
                channels.alert_donor(donor, text, key, "Urgent blood request")
                alerted += 1
        req.escalation_level, req.escalated_at = level, now
        scope = f"within {radius} km" if radius else "to every matching donor"
        note = f"Request #{req.id} had no offers yet, so it was widened {scope} ({alerted} more donor(s) alerted)."
        notify_account("hospital", req.hospital_id, note, req.id, dedupe_key=f"esc-h:{req.id}:{level}", commit=False)
        notify_account("patient", req.patient_id, note, req.id, dedupe_key=f"esc-p:{req.id}:{level}", commit=False)
        allocation.audit("system", 0, "request.escalated", "request", req.id, f"level {level}, {alerted} alerted")
        escalated += 1
    db.session.commit()
    return escalated


# -------------------------------------------------------------------- run them
def run_all(only=None):
    from utils import chat
    from utils.maintenance import expire_old_requests, retention_cleanup
    jobs = {
        "expire": lambda: expire_old_requests(force=True),
        "reminders": send_reminders,
        "escalate": escalate_requests,
        "deliver": channels.deliver_pending,
        "cleanup": lambda: {**retention_cleanup(current_app.config), "outbox": _purge()},
    }
    out = {}
    for name, fn in jobs.items():
        if only and name not in only:
            continue
        try:
            out[name] = fn()
        except Exception:                               # one failing job must not stop the others
            db.session.rollback()
            log.exception("job %s failed", name)
            out[name] = "error"
    return out


def _purge():
    n = channels.purge_old()
    db.session.commit()
    return n

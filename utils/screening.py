"""Screening reports: what a hospital records about a donor, and what the donor may read.

Rules that never bend:
* only the hospital that owns the offer (or camp) can write the report;
* the donor can read it only when the hospital marks it as shared, and never sees the hospital's internal note;
* patients, other donors, other hospitals and administrators cannot read it;
* BloodLink does not carry infectious-disease results; the page tells donors to ask the hospital in person.
"""
import io
from datetime import date, datetime, timedelta

from flask import current_app

from models import (ACTIVE_RESPONSES, OUTCOMES, REASONS, CampSignup, DonationResponse, ScreeningReport, db)
from utils import allocation
from utils.notifications import notify_donor

RANGES = {"hemoglobin": (3.0, 25.0, float), "systolic": (60, 260, int), "diastolic": (30, 160, int),
          "pulse": (30, 220, int), "temperature_c": (33.0, 43.0, float), "weight_kg": (20.0, 250.0, float)}
LABELS = {"hemoglobin": "Haemoglobin (g/dL)", "systolic": "Blood pressure, top (mmHg)",
          "diastolic": "Blood pressure, bottom (mmHg)", "pulse": "Pulse (per minute)",
          "temperature_c": "Temperature (\u00b0C)", "weight_kg": "Weight (kg)"}


class ScreeningError(Exception):
    pass


def parse_form(form):
    """Validate the hospital's form. Returns (clean values, list of problems)."""
    errors, data = [], {}
    outcome = (form.get("outcome") or "").strip()
    if outcome not in OUTCOMES:
        errors.append("Choose the screening outcome.")
    data["outcome"] = outcome
    for name, (low, high, kind) in RANGES.items():
        raw = (form.get(name) or "").strip()
        if raw == "":
            data[name] = None
            continue
        try:
            value = kind(float(raw)) if kind is int else float(raw)
        except ValueError:
            errors.append(f"{LABELS[name]}: enter a number.")
            continue
        if not (low <= value <= high):
            errors.append(f"{LABELS[name]}: expected between {low} and {high}.")
        else:
            data[name] = value
    reason = (form.get("reason") or "").strip()
    if outcome != OUTCOMES[0]:
        if reason not in REASONS:
            errors.append("Choose the main reason for deferral.")
        data["reason"] = reason
    else:
        data["reason"] = None
    days = 0
    if outcome == OUTCOMES[1]:
        try:
            days = int(form.get("deferral_days") or 0)
        except ValueError:
            days = -1
        if not 1 <= days <= 730:
            errors.append("Enter how many days (1 to 730) the donor should wait.")
    data["deferral_days"] = days
    data["message_to_donor"] = (form.get("message_to_donor") or "").strip()[:600] or None
    data["internal_note"] = (form.get("internal_note") or "").strip()[:600] or None
    data["shared_with_donor"] = form.get("shared_with_donor") == "on"
    return data, errors


def _apply(hospital, report, donor, data):
    for name in ("outcome", "reason", "hemoglobin", "systolic", "diastolic", "pulse", "temperature_c", "weight_kg",
                 "message_to_donor", "internal_note", "shared_with_donor"):
        setattr(report, name, data[name])
    if data["outcome"] == OUTCOMES[1]:
        report.deferral_until = date.today() + timedelta(days=data["deferral_days"])
    elif data["outcome"] == OUTCOMES[2]:
        report.deferral_until = None
    else:
        report.deferral_until = None
    # A deferral also keeps the donor out of matching until it ends.
    if report.deferral_until and (donor.deferred_until is None or donor.deferred_until < report.deferral_until):
        donor.deferred_until = report.deferral_until


def save_for_response(hospital, response_id, data):
    """Create or update the report for one donor offer. Returns the report."""
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.request.hospital_id != hospital.id:
        raise ScreeningError("That offer was not found.")
    report = resp.screening_report or ScreeningReport(response_id=resp.id, donor_id=resp.donor_id,
                                                      hospital_id=hospital.id)
    if report.hospital_id != hospital.id:
        raise ScreeningError("That offer was not found.")
    is_new = report.id is None
    _apply(hospital, report, resp.donor, data)
    db.session.add(report)
    db.session.flush()
    if data["outcome"] != OUTCOMES[0] and resp.response_status in ACTIVE_RESPONSES:
        allocation.mark_ineligible(hospital, resp.id, note=data["reason"],
                                   deferral_days=data["deferral_days"])     # commits
        resp = db.session.get(DonationResponse, response_id)
    _notify(resp.donor_id, report, resp.request_id, is_new, f"screen:{report.id}:{int(report.updated_at.timestamp()) if report.updated_at else 0}")
    allocation.audit("hospital", hospital.id, "screening.saved", "response", resp.id)
    db.session.commit()
    return report


def save_for_signup(hospital, signup_id, data):
    signup = db.session.get(CampSignup, signup_id)
    if signup is None or signup.camp.hospital_id != hospital.id:
        raise ScreeningError("That sign-up was not found.")
    report = signup.screening_report or ScreeningReport(camp_signup_id=signup.id, donor_id=signup.donor_id,
                                                        hospital_id=hospital.id)
    is_new = report.id is None
    _apply(hospital, report, signup.donor, data)
    db.session.add(report)
    db.session.flush()
    _notify(signup.donor_id, report, None, is_new, f"screen-camp:{report.id}:{datetime.utcnow():%Y%m%d%H%M%S}")
    allocation.audit("hospital", hospital.id, "screening.saved", "camp_signup", signup.id)
    db.session.commit()
    return report


def _notify(donor_id, report, request_id, is_new, key):
    if report.shared_with_donor:
        # The text carries no health details; they are shown only after the donor logs in.
        notify_donor(donor_id, "A hospital added a health check report for you. Open My health to read it.",
                     request_id, dedupe_key=key, commit=False)


# ----------------------------------------------------------------- what the donor sees
def reports_for_donor(donor):
    return (ScreeningReport.query.filter_by(donor_id=donor.id, shared_with_donor=True)
            .order_by(ScreeningReport.created_at.desc()).all())


def donor_eligibility(donor, today=None):
    """A plain-language answer to "can I donate, and if not, why?"."""
    from utils import badges
    today = today or date.today()
    reports = reports_for_donor(donor)
    deferred = donor.deferred_until and donor.deferred_until > today
    latest = next((r for r in reports if r.outcome != OUTCOMES[0]), None)
    summary = badges.summary(donor, today)
    if deferred:
        why = latest.reason if latest and latest.deferral_until == donor.deferred_until else None
        return {"state": "deferred", "until": donor.deferred_until,
                "days": (donor.deferred_until - today).days, "reason": why,
                "message": latest.message_to_donor if latest and latest.deferral_until == donor.deferred_until else None}
    if latest and latest.outcome == OUTCOMES[2] and latest is reports[0]:
        return {"state": "not_eligible", "reason": latest.reason, "message": latest.message_to_donor,
                "until": None, "days": None}
    if not summary["can_donate_now"]:
        return {"state": "resting", "until": summary["next_eligible"], "days": summary["days_left"],
                "reason": "Time to recover between donations", "message": None}
    return {"state": "eligible", "until": None, "days": 0, "reason": None, "message": None}


def purge_old(days):
    cutoff = datetime.utcnow() - timedelta(days=days)
    return ScreeningReport.query.filter(ScreeningReport.created_at < cutoff).delete(synchronize_session=False)


# --------------------------------------------------------------------------- PDF
def report_pdf(report):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle("Health check report")
    w, h = A4
    wine = colors.HexColor("#3a0714")
    c.setFillColor(wine); c.setFont("Helvetica-Bold", 20); c.drawString(20 * mm, h - 25 * mm, "Health check report")
    c.setFillColor(colors.black); c.setFont("Helvetica", 11)
    y = h - 38 * mm
    for line in (f"Donor: {report.donor.name}", f"Hospital: {report.hospital.hospital_name}, {report.hospital.city}",
                 f"Date: {report.created_at:%d %B %Y}", f"Outcome: {report.outcome}"):
        c.drawString(20 * mm, y, line); y -= 7 * mm
    if report.reason:
        c.drawString(20 * mm, y, f"Main reason: {report.reason}"); y -= 7 * mm
    if report.deferral_until:
        c.drawString(20 * mm, y, f"Please wait until: {report.deferral_until:%d %B %Y}"); y -= 7 * mm
    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12); c.drawString(20 * mm, y, "Measurements"); y -= 7 * mm
    c.setFont("Helvetica", 11)
    for name, label in LABELS.items():
        value = getattr(report, name)
        if value is not None:
            c.drawString(24 * mm, y, f"{label}: {value}"); y -= 6 * mm
    if report.message_to_donor:
        y -= 4 * mm; c.setFont("Helvetica-Bold", 12); c.drawString(20 * mm, y, "Message from the hospital"); y -= 7 * mm
        c.setFont("Helvetica", 11)
        text = report.message_to_donor
        while text:
            c.drawString(24 * mm, y, text[:90]); text = text[90:]; y -= 6 * mm
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(20 * mm, 20 * mm, "Written by the hospital. Not a diagnosis. Ask the hospital about any other test results.")
    c.showPage(); c.save()
    return buf.getvalue()

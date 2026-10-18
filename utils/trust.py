"""Check-in codes and donation certificates.

Both are tamper-proof without a lookup table: a short code is the record id plus a keyed hash
(HMAC with SECRET_KEY) of the facts it vouches for. Change the facts, or guess an id, and the
hash no longer matches.
"""
import hashlib
import hmac
import io
import re
from datetime import datetime

import segno
from flask import current_app, url_for

from models import RESP_COMPLETED, ACTIVE_RESPONSES, DonationResponse, db


def _mac(*parts, size=8):
    key = current_app.config["SECRET_KEY"].encode()
    return hmac.new(key, "|".join(str(p) for p in parts).encode(), hashlib.sha256).hexdigest()[:size].upper()


# ------------------------------------------------------------------- check-in
def checkin_code(resp):
    """Short code the donor can read out: 17-4F2A9C. Tied to the appointment time."""
    when = resp.appointment_at.strftime("%Y%m%d%H%M") if resp.appointment_at else "none"
    return f"{resp.id}-{_mac('checkin', resp.id, resp.donor_id, when, size=6)}"


def resolve_checkin(code):
    """Return the DonationResponse for a valid code, else None."""
    m = re.fullmatch(r"\s*(?:BL-)?(\d{1,9})-([0-9A-F]{6})\s*", code or "", re.I)
    if not m:
        return None
    resp = db.session.get(DonationResponse, int(m.group(1)))
    if resp is None or not hmac.compare_digest(checkin_code(resp), f"{resp.id}-{m.group(2).upper()}"):
        return None
    return resp


def checkin_url(resp):
    return url_for("trust.checkin_scan", code=checkin_code(resp), _external=True)


def qr_data_uri(text, scale=6):
    return segno.make(text, error="m").svg_data_uri(scale=scale, border=2)


def can_check_in(resp):
    return resp.response_status in ACTIVE_RESPONSES and resp.appointment_at is not None


# ---------------------------------------------------------------- certificates
def certificate_code(resp):
    when = resp.verified_at.strftime("%Y%m%d") if resp.verified_at else "none"
    return f"BL-{resp.id:05d}-{_mac('cert', resp.id, resp.donor_id, resp.units_collected, when)}"


def resolve_certificate(code):
    m = re.fullmatch(r"\s*BL-(\d{1,9})-([0-9A-F]{8})\s*", code or "", re.I)
    if not m:
        return None
    resp = db.session.get(DonationResponse, int(m.group(1)))
    if (resp is None or resp.response_status != RESP_COMPLETED
            or not hmac.compare_digest(certificate_code(resp), f"BL-{resp.id:05d}-{m.group(2).upper()}")):
        return None
    return resp


def public_name(donor):
    """First name and the initial of the last name only, for the public verification page."""
    parts = (donor.name or "").split()
    if not parts or donor.name == "Deleted donor":
        return "Name withdrawn"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def certificate_pdf(resp):
    """A one-page A4 PDF. Returns bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    code = certificate_code(resp)
    verify = url_for("trust.verify", code=code, _external=True)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setTitle("BloodLink donation certificate")
    w, h = landscape(A4)
    wine, red = colors.HexColor("#3a0714"), colors.HexColor("#c8102e")
    c.setStrokeColor(wine); c.setLineWidth(3); c.rect(12 * mm, 12 * mm, w - 24 * mm, h - 24 * mm)
    c.setStrokeColor(red); c.setLineWidth(1); c.rect(16 * mm, 16 * mm, w - 32 * mm, h - 32 * mm)
    c.setFillColor(red); c.setFont("Helvetica-Bold", 14); c.drawCentredString(w / 2, h - 38 * mm, "BLOODLINK")
    c.setFillColor(wine); c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(w / 2, h - 58 * mm, "Certificate of Blood Donation")
    c.setFont("Helvetica", 14); c.setFillColor(colors.black)
    c.drawCentredString(w / 2, h - 82 * mm, "This certifies that")
    c.setFont("Helvetica-Bold", 28); c.setFillColor(wine)
    c.drawCentredString(w / 2, h - 98 * mm, resp.donor.name)
    c.setFont("Helvetica", 14); c.setFillColor(colors.black)
    when = (resp.verified_at or datetime.utcnow()).strftime("%d %B %Y")
    units = resp.units_collected or 1
    c.drawCentredString(w / 2, h - 116 * mm, f"donated {units} unit{'s' if units != 1 else ''} of blood on {when}")
    c.drawCentredString(w / 2, h - 125 * mm, f"at {resp.request.hospital.hospital_name}, {resp.request.hospital.city}.")
    c.setFont("Helvetica-Oblique", 12)
    c.drawCentredString(w / 2, h - 142 * mm, "Thank you. Your gift helps someone in need.")
    qr = io.BytesIO(); segno.make(verify, error="m").save(qr, kind="png", scale=4, border=1)
    qr.seek(0); c.drawImage(ImageReader(qr), 28 * mm, 24 * mm, 30 * mm, 30 * mm)
    c.setFont("Helvetica", 9); c.setFillColor(colors.black)
    c.drawString(62 * mm, 44 * mm, "Verification code")
    c.setFont("Helvetica-Bold", 13); c.drawString(62 * mm, 37 * mm, code)
    c.setFont("Helvetica", 8)
    c.drawString(62 * mm, 30 * mm, "Scan the code or enter it on the BloodLink verification page.")
    c.drawRightString(w - 28 * mm, 30 * mm, "Confirmed by the hospital. Not a medical record.")
    c.showPage(); c.save()
    return buf.getvalue()

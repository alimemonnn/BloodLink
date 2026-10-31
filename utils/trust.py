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

from models import RESP_COMPLETED, ACTIVE_RESPONSES, CampSignup, DonationResponse, db


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


def camp_checkin_code(signup):
    """Short code for a camp place: C12-4F2A9C. Tied to the camp and its start time."""
    when = signup.camp.starts_at.strftime("%Y%m%d%H%M")
    return f"C{signup.id}-{_mac('campcheckin', signup.id, signup.donor_id, signup.camp_id, when, size=6)}"


def resolve_camp_checkin(code):
    """Return the CampSignup for a valid camp code, else None."""
    m = re.fullmatch(r"\s*(?:BL-)?C(\d{1,9})-([0-9A-F]{6})\s*", code or "", re.I)
    if not m:
        return None
    signup = db.session.get(CampSignup, int(m.group(1)))
    if signup is None or not hmac.compare_digest(camp_checkin_code(signup), f"C{signup.id}-{m.group(2).upper()}"):
        return None
    return signup


def camp_checkin_url(signup):
    return url_for("trust.checkin_scan", code=camp_checkin_code(signup), _external=True)


def can_camp_check_in(signup):
    return signup.status in ("Signed up", "Attended") and not signup.camp.is_cancelled


def can_check_in(resp):
    return resp.response_status in ACTIVE_RESPONSES and resp.appointment_at is not None


# ---------------------------------------------------------------- certificates
def certificate_code(resp):
    when = resp.verified_at.strftime("%Y%m%d") if resp.verified_at else "none"
    return f"BL-{resp.id:05d}-{_mac('cert', resp.id, resp.donor_id, resp.units_collected, when)}"


def camp_certificate_code(signup):
    when = signup.verified_at.strftime("%Y%m%d") if signup.verified_at else "none"
    return f"BC-{signup.id:05d}-{_mac('campcert', signup.id, signup.donor_id, signup.units, when)}"


def code_for(record):
    return camp_certificate_code(record) if isinstance(record, CampSignup) else certificate_code(record)


def resolve_certificate(code):
    """Return the confirmed donation (a DonationResponse or a CampSignup) behind a valid code, else None."""
    m = re.fullmatch(r"\s*(BL|BC)-(\d{1,9})-([0-9A-F]{8})\s*", code or "", re.I)
    if not m:
        return None
    kind, rid, mac = m.group(1).upper(), int(m.group(2)), m.group(3).upper()
    if kind == "BL":
        rec = db.session.get(DonationResponse, rid)
        ok = rec is not None and rec.response_status == RESP_COMPLETED
        expected = f"BL-{rid:05d}-{mac}"
    else:
        rec = db.session.get(CampSignup, rid)
        ok = rec is not None and rec.status == "Donated"
        expected = f"BC-{rid:05d}-{mac}"
    if not ok or not hmac.compare_digest(code_for(rec), expected):
        return None
    return rec


def certificate_facts(record):
    """The few facts a certificate and the public verification page may show."""
    if isinstance(record, CampSignup):
        return {"donor": record.donor, "units": record.units or 1, "when": record.verified_at,
                "place": record.camp.hospital.hospital_name, "city": record.camp.city,
                "extra": f"at the donation camp \"{record.camp.title}\""}
    h = record.request.hospital
    return {"donor": record.donor, "units": record.units_collected or 1, "when": record.verified_at,
            "place": h.hospital_name, "city": h.city, "extra": None}


def public_name(donor):
    """First name and the initial of the last name only, for the public verification page."""
    parts = (donor.name or "").split()
    if not parts or donor.name == "Deleted donor":
        return "Name withdrawn"
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def certificate_pdf(record):
    """A one-page A4 PDF for a confirmed donation. Returns bytes."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    f = certificate_facts(record)
    code = code_for(record)
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
    c.drawCentredString(w / 2, h - 98 * mm, f["donor"].name)
    c.setFont("Helvetica", 14); c.setFillColor(colors.black)
    when = (f["when"] or datetime.utcnow()).strftime("%d %B %Y")
    units = f["units"]
    c.drawCentredString(w / 2, h - 116 * mm, f"donated {units} unit{'s' if units != 1 else ''} of blood on {when}")
    c.drawCentredString(w / 2, h - 125 * mm, f"at {f['place']}, {f['city']}.")
    if f["extra"]:
        c.setFont("Helvetica", 12); c.drawCentredString(w / 2, h - 133 * mm, f["extra"][3:] if f["extra"].startswith("at ") else f["extra"])
    c.setFont("Helvetica-Oblique", 12)
    c.drawCentredString(w / 2, h - 146 * mm, "Thank you. Your gift helps someone in need.")
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

"""Emergency requests posted by a hospital itself (a walk-in patient, a road accident, a surgery that cannot wait).

The request is approved at once, because the hospital that would approve it is the one posting it. To keep every
existing page working, such requests belong to one inactive "walk-in" patient record per hospital that nobody can log in as.
"""
import secrets
from datetime import datetime, timedelta

from models import STATUS_APPROVED, BloodRequest, Patient, db
from utils import allocation
from utils.notifications import notify_matching_donors

BLOOD = ("A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-")
HOURS = {6: "6 hours", 12: "12 hours", 24: "24 hours", 48: "48 hours", 72: "3 days"}


class EmergencyError(Exception):
    pass


def walkin_patient(hospital):
    email = f"walkin-h{hospital.id}@bloodlink.invalid"
    patient = Patient.query.filter_by(email=email).first()
    if patient is None:
        patient = Patient(name=f"Walk-in patients ({hospital.hospital_name})", email=email, phone=hospital.phone or "-",
                          city=hospital.city or "-", is_active=False, policy_version="hospital-walkin")
        patient.set_password(secrets.token_urlsafe(32))       # random and thrown away: no one can log in
        db.session.add(patient)
        db.session.flush()
    return patient


def create(hospital, form):
    errors = []
    group = (form.get("blood_group_required") or "").strip()
    if group not in BLOOD:
        errors.append("Choose the blood group needed.")
    try:
        units = int(form.get("units_required") or 0)
    except ValueError:
        units = 0
    if not 1 <= units <= 20:
        errors.append("Units needed must be between 1 and 20.")
    urgency = form.get("urgency") if form.get("urgency") in ("Urgent", "Critical") else "Critical"
    try:
        hours = int(form.get("hours") or 24)
    except ValueError:
        hours = 24
    if hours not in HOURS:
        hours = 24
    label = (form.get("patient_label") or "").strip()[:60] or "Hospital emergency"
    description = (form.get("description") or "").strip()[:600] or None
    if errors:
        raise EmergencyError(" ".join(errors))
    now = datetime.utcnow()
    req = BloodRequest(
        patient_id=walkin_patient(hospital).id, hospital_id=hospital.id, patient_name=label,
        blood_group_required=group, units_required=units, urgency=urgency, location=hospital.city or hospital.hospital_name,
        contact_number=hospital.phone or "-", description=description, status=STATUS_APPROVED, hospital_verified=True,
        hospital_notes="Posted by the hospital as an emergency.", approved_at=now, expiry_date=now + timedelta(hours=hours),
        source="hospital")
    db.session.add(req)
    db.session.flush()
    allocation.audit("hospital", hospital.id, "request.emergency", "request", req.id)
    db.session.commit()
    notified = notify_matching_donors(req)
    return req, notified

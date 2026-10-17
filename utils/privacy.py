"""Consent records, data export and account erasure.

Erasure rule: personal data is removed. If the person has a VERIFIED donation or
a request that fed the hospital's records, the row stays but only in anonymised
form, so unit counts remain correct without keeping anyone's identity.
"""
import secrets
from datetime import datetime

from flask import current_app

from models import (AccountNotification, BloodRequest, ConsentRecord,
                    DonationResponse, Notification, RESP_COMPLETED, LIVE_STATUSES, db)
from utils import allocation, chat


def record_consent(role, user_id, purposes, granted=True):
    """Store one ConsentRecord per purpose (does not commit)."""
    version = current_app.config["POLICY_VERSION"]
    for purpose in purposes:
        db.session.add(ConsentRecord(subject_role=role, subject_id=user_id, purpose=purpose,
                                     granted=granted, policy_version=version))


def set_consent(role, user_id, purpose, granted):
    record_consent(role, user_id, [purpose], granted)


def _scrub_identity(user, role):
    user.email = f"deleted-{role}-{user.id}@deleted.invalid"
    user.phone = ""
    user.password_hash = "!" + secrets.token_hex(16)     # nobody can log in
    user.is_active = False
    user.last_login_at = None


def _drop_personal_rows(role, user_id):
    ConsentRecord.query.filter_by(subject_role=role, subject_id=user_id).delete()
    AccountNotification.query.filter_by(role=role, user_id=user_id).delete()


def erase_donor(donor):
    """Remove a donor's personal data. Returns 'deleted' or 'anonymised'."""
    uid = donor.id
    chat.erase_for("donor", uid)
    for resp in list(donor.responses):                   # offers that never became a donation
        if resp.response_status != RESP_COMPLETED:
            if resp.is_active:
                allocation.cancel_response(resp.id, "donor", uid, "account deleted")
    Notification.query.filter_by(donor_id=uid).delete()
    _drop_personal_rows("donor", uid)
    db.session.expire_all()
    donor = db.session.get(type(donor), uid)
    if any(r.response_status == RESP_COMPLETED for r in donor.responses):
        for r in list(donor.responses):
            if r.response_status != RESP_COMPLETED:
                db.session.delete(r)
        donor.name, donor.city, donor.area = "Deleted donor", "", None
        donor.blood_group = "N/A"
        donor.last_donation_date = donor.deferred_until = None
        donor.share_contact_consent = donor.email_opt_in = False
        donor.terms_accepted_at = donor.age_confirmed_at = donor.health_data_consent_at = None
        _scrub_identity(donor, "donor")
        result = "anonymised"
    else:
        db.session.delete(donor)
        result = "deleted"
    db.session.commit()
    return result


def erase_patient(patient):
    """Cancel live requests, scrub personal fields, remove the account."""
    uid = patient.id
    chat.erase_for("patient", uid)
    for req in list(patient.requests):
        if req.status in LIVE_STATUSES:
            allocation.close_request(req.id, "patient", uid, "account deleted")
    db.session.expire_all()
    patient = db.session.get(type(patient), uid)
    for req in patient.requests:
        req.patient_name, req.contact_number = "Anonymised", ""
        req.description = req.hospital_notes = None
        req.anonymised_at = datetime.utcnow()
    _drop_personal_rows("patient", uid)
    if patient.requests:
        patient.name, patient.city, patient.address = "Deleted user", "", None
        _scrub_identity(patient, "patient")
        result = "anonymised"
    else:
        db.session.delete(patient)
        result = "deleted"
    db.session.commit()
    return result


def export_data(role, user):
    """Everything BloodLink holds about this account, as a plain dict."""
    base = {"account_type": role, "exported_at": datetime.utcnow().isoformat() + "Z",
            "policy_version": user.policy_version if hasattr(user, "policy_version") else None}
    consents = [{"purpose": c.purpose, "granted": c.granted, "policy_version": c.policy_version,
                 "at": c.created_at.isoformat()}
                for c in ConsentRecord.query.filter_by(subject_role=role, subject_id=user.id)]
    if role == "donor":
        base["profile"] = {k: _s(getattr(user, k)) for k in (
            "name", "email", "phone", "blood_group", "city", "area", "last_donation_date",
            "availability", "share_contact_consent", "email_opt_in", "deferred_until", "created_at")}
        base["responses"] = [{"request_id": r.request_id, "status": r.response_status,
                              "units_pledged": r.units_pledged, "units_collected": r.units_collected,
                              "responded_at": _s(r.response_date), "verified_at": _s(r.verified_at)}
                             for r in user.responses]
        base["notifications"] = [{"message": n.message, "at": _s(n.created_at)}
                                 for n in Notification.query.filter_by(donor_id=user.id)]
        base["chat_messages_sent"] = chat.export_for("donor", user.id)
    elif role == "patient":
        base["profile"] = {k: _s(getattr(user, k)) for k in ("name", "email", "phone", "city", "created_at")}
        base["requests"] = [{"id": r.id, "patient_name": r.patient_name, "blood_group": r.blood_group_required,
                             "units_required": r.units_required, "units_confirmed": r.units_confirmed,
                             "status": r.status, "urgency": r.urgency, "location": r.location,
                             "contact_number": r.contact_number, "description": r.description,
                             "created_at": _s(r.created_at)} for r in user.requests]
        base["chat_messages_sent"] = chat.export_for("patient", user.id)
    elif role == "hospital":
        base["profile"] = {k: _s(getattr(user, k)) for k in (
            "hospital_name", "email", "phone", "address", "city", "is_verified", "created_at")}
        base["requests_handled"] = [{"id": r.id, "status": r.status, "blood_group": r.blood_group_required,
                                     "units_required": r.units_required, "units_confirmed": r.units_confirmed}
                                    for r in user.requests]
        base["chat_messages_sent"] = chat.export_for("hospital", user.id)
    base["consents"] = consents
    return base


def _s(v):
    return v.isoformat() if hasattr(v, "isoformat") else v

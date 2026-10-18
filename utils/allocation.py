"""Multi-donor blood allocation: the single place that changes request totals.

The scenario this solves
------------------------
A patient needs 3 units and three compatible donors offer to help.

    required = 3
    Donor A confirmed 1  -> confirmed 1, remaining 2, status "Partially Fulfilled"
    Donor B confirmed 1  -> confirmed 2, remaining 1, status "Partially Fulfilled"
    Donor C confirmed 1  -> confirmed 3, remaining 0, status "Fulfilled"

Rules enforced here (never only in the browser)
-----------------------------------------------
1. Only a hospital that owns the request can confirm a donation.
2. Totals are derived from donation records, not from a stored counter.
3. A confirmation can never push the total above ``required``.
4. A response can be confirmed once only (a retry is rejected, not counted twice).
5. The request row is locked while confirming, so two simultaneous
   confirmations cannot both claim the last unit.
   - PostgreSQL: ``SELECT ... FOR UPDATE``.
   - SQLite: a no-op UPDATE takes the single database write lock first.
"""
from datetime import date, datetime, timedelta

from flask import current_app
from sqlalchemy import func, update

from models import (ACTIVE_RESPONSES, OPEN_STATUSES, RESP_CANCELLED,
                    RESP_COMPLETED, RESP_CONTACTED, RESP_INELIGIBLE,
                    RESP_INTERESTED, RESP_SCHEDULED, STATUS_CANCELLED,
                    STATUS_EXPIRED, STATUS_FULFILLED, STATUS_PARTIAL,
                    AuditLog, BloodRequest, DonationResponse, Donor, db)
from models import LIVE_STATUSES
from utils.matching import can_donate
from utils import chat
from utils.notifications import notify_account, notify_donor


class AllocationError(Exception):
    """A rule was broken. The message is safe to show to the user."""


class NotAuthorized(AllocationError):
    pass


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def progress(req):
    """Numbers shown on every progress bar."""
    return {
        "required": req.required,
        "pledged": req.units_pledged,
        "confirmed": req.units_confirmed,
        "remaining": req.units_remaining,
        "percent": req.progress_percent,
    }


def remaining_formula(required, confirmed):
    return max(0, required - confirmed)


def percent_formula(required, confirmed):
    if not required or required <= 0:
        return 0
    return min(100, confirmed / required * 100)


def audit(role, actor_id, action, target_type, target_id, detail=None):
    db.session.add(AuditLog(actor_role=role, actor_id=actor_id, action=action,
                            target_type=target_type, target_id=target_id,
                            detail=(detail or "")[:255]))


def _lock_request(request_id):
    """Lock the request row for the rest of this transaction and re-read it."""
    db.session.expire_all()
    # SQLite ignores FOR UPDATE, so a harmless write takes the write lock instead.
    db.session.execute(update(BloodRequest).where(BloodRequest.id == request_id)
                       .values(updated_at=BloodRequest.updated_at))
    req = (db.session.query(BloodRequest).filter_by(id=request_id)
           .with_for_update().populate_existing().one_or_none())
    if req is None:
        raise AllocationError("That request no longer exists.")
    return req


def _confirmed_units(request_id):
    total = (db.session.query(func.coalesce(func.sum(DonationResponse.units_collected), 0))
             .filter(DonationResponse.request_id == request_id,
                     DonationResponse.response_status == RESP_COMPLETED).scalar())
    return int(total or 0)


def _load_response_locked(response_id):
    resp = db.session.get(DonationResponse, response_id)
    if resp is None:
        raise AllocationError("That donor response does not exist.")
    req = _lock_request(resp.request_id)
    resp = db.session.query(DonationResponse).filter_by(id=response_id)\
        .populate_existing().one()
    return req, resp


def recompute_status(req):
    """Set Open / Partially Fulfilled / Fulfilled from the donation records."""
    confirmed = _confirmed_units(req.id)
    if req.status in OPEN_STATUSES or req.status == STATUS_FULFILLED:
        if confirmed >= req.required:
            req.status = STATUS_FULFILLED
            req.closed_at = req.closed_at or datetime.utcnow()
        elif confirmed > 0:
            req.status = STATUS_PARTIAL
        else:
            req.status = "Approved"
    return confirmed


def _close_outstanding(req, note, reason_key):
    """Cancel every still-active response and tell those donors."""
    count = 0
    for resp in list(req.responses):
        if resp.response_status in ACTIVE_RESPONSES:
            resp.response_status = RESP_CANCELLED
            resp.hospital_note = note[:255]
            chat.add_event(resp, f"This request was closed: {note}")
            notify_donor(resp.donor_id, f"Request #{req.id} is closed: {note}",
                         req.id, dedupe_key=f"{reason_key}:{req.id}:{resp.donor_id}",
                         commit=False)
            count += 1
    return count


# ----------------------------------------------------------------------
# Donor actions
# ----------------------------------------------------------------------
def pledge(donor, request_id, units=1, consent_to_share=False):
    """A donor offers to help. This is willingness only, never medical approval."""
    if not consent_to_share:
        raise AllocationError("Please agree to share your name and phone number "
                              "with the hospital and patient for this request.")
    try:
        units = int(units)
    except (TypeError, ValueError):
        raise AllocationError("Units must be a whole number.")
    cap = current_app.config["MAX_UNITS_PER_DONOR_DONATION"]
    if units < 1 or units > cap:
        raise AllocationError(f"You can offer between 1 and {cap} unit(s).")
    try:
        req = _lock_request(request_id)
        if req.status not in OPEN_STATUSES or req.has_expired:
            raise AllocationError("This request is no longer open for responses.")
        if not donor.is_active:
            raise NotAuthorized("Your account is not active.")
        if donor.availability != "Available":
            raise AllocationError("Set yourself as Available before responding.")
        if not can_donate(donor.blood_group, req.blood_group_required):
            raise AllocationError("Your blood group is not compatible with this request.")
        if not donor.is_eligible:
            raise AllocationError(f"The usual rest period after a donation has not passed. "
                                  f"You can respond again in {donor.days_until_eligible} days.")
        if donor.deferred_until and donor.deferred_until > date.today():
            raise AllocationError("A hospital has deferred your donation until "
                                  f"{donor.deferred_until:%d %b %Y}.")
        remaining = req.units_remaining
        if units > remaining:
            raise AllocationError(f"Only {remaining} unit(s) are still needed.")

        resp = DonationResponse.query.filter_by(donor_id=donor.id, request_id=req.id).first()
        if resp is not None and resp.response_status != RESP_CANCELLED:
            raise AllocationError("You have already responded to this request.")
        if resp is None:
            resp = DonationResponse(donor_id=donor.id, request_id=req.id)
            db.session.add(resp)
        resp.response_status = RESP_INTERESTED
        resp.units_pledged = units
        resp.units_collected = 0
        resp.hospital_note = None
        resp.contact_consent_at = datetime.utcnow()
        db.session.flush()
        chat.add_event(resp, f"The donor offered {units} unit(s). Use this chat to agree a time with the hospital.")
        notify_account("hospital", req.hospital_id,
                       f"A donor offered {units} unit(s) for request #{req.id}.",
                       req.id, dedupe_key=f"pledge:{resp.id}:{resp.contact_consent_at.isoformat()}",
                       commit=False)
        notify_account("patient", req.patient_id,
                       f"A compatible donor offered to help with request #{req.id}.",
                       req.id, dedupe_key=f"pledge-p:{resp.id}:{resp.contact_consent_at.isoformat()}",
                       commit=False)
        audit("donor", donor.id, "response.create", "request", req.id)
        db.session.commit()
        return resp
    except Exception:
        db.session.rollback()
        raise


def cancel_response(response_id, actor_role, actor_id, note=None):
    """The donor (or the hospital, for a no-show) cancels an outstanding response."""
    try:
        req, resp = _load_response_locked(response_id)
        if actor_role == "donor" and resp.donor_id != actor_id:
            raise NotAuthorized("This response is not yours.")
        if actor_role == "hospital" and req.hospital_id != actor_id:
            raise NotAuthorized("This request belongs to another hospital.")
        if resp.response_status == RESP_COMPLETED:
            raise AllocationError("A verified donation cannot be cancelled.")
        if resp.response_status not in ACTIVE_RESPONSES:
            raise AllocationError("This response is already closed.")
        resp.response_status = RESP_CANCELLED
        resp.hospital_note = (note or "")[:255] or None
        chat.add_event(resp, "The donor cancelled this offer." if actor_role == "donor"
                       else "The hospital cancelled this offer.")
        if actor_role == "donor":
            notify_account("hospital", req.hospital_id,
                           f"A donor cancelled their offer for request #{req.id}.",
                           req.id, dedupe_key=f"cancel:{resp.id}:{datetime.utcnow().isoformat()}",
                           commit=False)
        else:
            notify_donor(resp.donor_id, f"The hospital cancelled your offer for request #{req.id}.",
                         req.id, dedupe_key=f"hcancel:{resp.id}:{datetime.utcnow().isoformat()}",
                         commit=False)
        audit(actor_role, actor_id, "response.cancel", "response", resp.id)
        db.session.commit()
        return resp
    except Exception:
        db.session.rollback()
        raise


# ----------------------------------------------------------------------
# Hospital actions
# ----------------------------------------------------------------------
def _hospital_response(hospital, response_id, allowed=ACTIVE_RESPONSES):
    req, resp = _load_response_locked(response_id)
    if req.hospital_id != hospital.id:
        raise NotAuthorized("This request belongs to another hospital.")
    if resp.response_status == RESP_COMPLETED:
        raise AllocationError("This donation has already been confirmed.")
    if resp.response_status not in allowed:
        raise AllocationError("This donor response is no longer active.")
    if req.status not in OPEN_STATUSES:
        raise AllocationError("This request is no longer open.")
    return req, resp


def mark_contacted(hospital, response_id):
    try:
        req, resp = _hospital_response(hospital, response_id, (RESP_INTERESTED,))
        resp.response_status = RESP_CONTACTED
        chat.add_event(resp, "The hospital marked this donor as contacted.")
        notify_donor(resp.donor_id, f"The hospital contacted you about request #{req.id}.",
                     req.id, dedupe_key=f"contacted:{resp.id}", commit=False)
        audit("hospital", hospital.id, "response.contacted", "response", resp.id)
        db.session.commit()
        return resp
    except Exception:
        db.session.rollback()
        raise


def schedule_appointment(hospital, response_id, when, note=None):
    if not isinstance(when, datetime):
        raise AllocationError("Enter a valid appointment date and time.")
    if when < datetime.utcnow() - timedelta(minutes=5):
        raise AllocationError("The appointment cannot be in the past.")
    try:
        req, resp = _hospital_response(hospital, response_id, (RESP_INTERESTED, RESP_CONTACTED, RESP_SCHEDULED))
        resp.response_status = RESP_SCHEDULED
        resp.appointment_at = when
        resp.hospital_note = (note or "")[:255] or None
        chat.add_event(resp, f"Appointment scheduled for {when:%A %d %b %Y, %H:%M}.")
        notify_donor(resp.donor_id,
                     f"Appointment for request #{req.id}: {when:%d %b %Y, %H:%M}.",
                     req.id, dedupe_key=f"appt:{resp.id}:{when.isoformat()}", commit=False)
        audit("hospital", hospital.id, "response.scheduled", "response", resp.id)
        db.session.commit()
        return resp
    except Exception:
        db.session.rollback()
        raise


def mark_ineligible(hospital, response_id, note=None, deferral_days=0):
    """A hospital screening decision. The donor is skipped by matching until deferred_until."""
    try:
        deferral_days = max(0, min(int(deferral_days or 0), 730))
    except (TypeError, ValueError):
        deferral_days = 0
    try:
        req, resp = _hospital_response(hospital, response_id)
        resp.response_status = RESP_INELIGIBLE
        resp.hospital_note = (note or "")[:255] or None
        if deferral_days:
            resp.donor.deferred_until = date.today() + timedelta(days=deferral_days)
        chat.add_event(resp, "The hospital could not accept this donation this time.")
        notify_donor(resp.donor_id,
                     f"The hospital could not accept your donation for request #{req.id} this time.",
                     req.id, dedupe_key=f"inelig:{resp.id}", commit=False)
        audit("hospital", hospital.id, "response.ineligible", "response", resp.id)
        db.session.commit()
        return resp
    except Exception:
        db.session.rollback()
        raise


def confirm_donation(hospital, response_id, units=None):
    """Record units actually collected. The ONLY way blood is counted."""
    try:
        req, resp = _hospital_response(hospital, response_id)
        if req.has_expired:
            raise AllocationError("This request has expired.")
        units = resp.units_pledged if units in (None, "") else units
        try:
            units = int(units)
        except (TypeError, ValueError):
            raise AllocationError("Units collected must be a whole number.")
        cap = current_app.config["MAX_UNITS_PER_DONOR_DONATION"]
        if units < 1 or units > cap:
            raise AllocationError(f"Units collected from one donor must be between 1 and {cap}.")
        remaining = max(0, req.required - _confirmed_units(req.id))
        if units > remaining:
            raise AllocationError(f"Only {remaining} unit(s) are still needed; "
                                  "this would exceed the request.")
        donor = resp.donor
        if donor.deferred_until and donor.deferred_until > date.today():
            raise AllocationError("This donor is deferred and cannot be confirmed.")

        now = datetime.utcnow()
        resp.response_status = RESP_COMPLETED
        resp.units_collected = units
        resp.donation_date = now.date()
        resp.verified_by_hospital_id = hospital.id
        resp.verified_at = now
        donor.last_donation_date = now.date()
        donor.refresh_eligibility()
        db.session.flush()
        chat.add_event(resp, f"Donation confirmed by the hospital: {units} unit(s). Thank you!")

        confirmed = recompute_status(req)
        left = max(0, req.required - confirmed)
        notify_donor(donor.id, f"Thank you. The hospital verified your donation for request #{req.id}.",
                     req.id, dedupe_key=f"verified:{resp.id}", commit=False)
        notify_account("patient", req.patient_id,
                       f"Request #{req.id}: {confirmed} of {req.required} unit(s) confirmed, {left} remaining.",
                       req.id, dedupe_key=f"progress:{req.id}:{confirmed}", commit=False)
        if req.status == STATUS_FULFILLED:
            _close_outstanding(req, "all required units have been collected", "done")
            notify_account("patient", req.patient_id, f"Request #{req.id} is fulfilled.",
                           req.id, dedupe_key=f"fulfilled:{req.id}", commit=False)
        audit("hospital", hospital.id, "donation.confirm", "response", resp.id, f"units={units}")
        db.session.commit()
        return resp
    except Exception:
        db.session.rollback()
        raise


def close_request(request_id, actor_role, actor_id, reason=None):
    """Cancel / close a request (patient, or hospital with a mandatory reason)."""
    reason = (reason or "").strip()
    if actor_role == "hospital" and not reason:
        raise AllocationError("Please give a reason for closing the request.")
    if len(reason) > 255:
        raise AllocationError("The reason must be 255 characters or fewer.")
    try:
        req = _lock_request(request_id)
        if actor_role == "patient" and req.patient_id != actor_id:
            raise NotAuthorized("This is not your request.")
        if actor_role == "hospital" and req.hospital_id != actor_id:
            raise NotAuthorized("This request belongs to another hospital.")
        if req.status not in LIVE_STATUSES:
            raise AllocationError("This request is already closed.")
        req.status = STATUS_CANCELLED
        req.closed_reason = reason or f"Cancelled by {actor_role}"
        req.closed_at = datetime.utcnow()
        _close_outstanding(req, "the request was cancelled", "cancelled")
        other = ("hospital", req.hospital_id) if actor_role == "patient" else ("patient", req.patient_id)
        notify_account(other[0], other[1], f"Request #{req.id} was cancelled.", req.id,
                       dedupe_key=f"cancelled-req:{req.id}", commit=False)
        audit(actor_role, actor_id, "request.cancel", "request", req.id)
        db.session.commit()
        return req
    except Exception:
        db.session.rollback()
        raise


def expire_request(request_id):
    """Close a request whose deadline passed before all units were collected."""
    try:
        req = _lock_request(request_id)
        if req.status not in LIVE_STATUSES or not req.has_expired:
            db.session.rollback()
            return False
        req.status = STATUS_EXPIRED
        req.closed_at = datetime.utcnow()
        _close_outstanding(req, "the request expired", "expired")
        notify_account("patient", req.patient_id, f"Request #{req.id} expired.", req.id,
                       dedupe_key=f"expired:{req.id}", commit=False)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        raise


# ----------------------------------------------------------------------
# Consistency check (also available as: flask check-consistency)
# ----------------------------------------------------------------------
def check_consistency():
    problems = []
    for r in DonationResponse.query.all():
        if r.response_status == RESP_COMPLETED and (r.units_collected or 0) < 1:
            problems.append(f"response {r.id}: completed but no units recorded")
        if r.response_status != RESP_COMPLETED and (r.units_collected or 0) > 0:
            problems.append(f"response {r.id}: units recorded but status is {r.response_status}")
    for req in BloodRequest.query.all():
        c = req.units_confirmed
        if c > req.required:
            problems.append(f"request {req.id}: confirmed {c} exceeds required {req.required}")
        if req.status == STATUS_FULFILLED and c < req.required and not req.closed_reason == "legacy":
            problems.append(f"request {req.id}: Fulfilled but only {c}/{req.required} units confirmed")
        if req.status == STATUS_PARTIAL and not (0 < c < req.required):
            problems.append(f"request {req.id}: Partially Fulfilled but confirmed is {c}")
        if req.status == "Approved" and c > 0:
            problems.append(f"request {req.id}: Open but {c} unit(s) already confirmed")
    return problems

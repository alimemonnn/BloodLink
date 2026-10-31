"""A donor says "I donated"; the hospital checks. The claim never counts blood.

Only the hospital's *Confirm donation* adds units, badges and a certificate. A claim is a request for the hospital to
look for the record, so a donor cannot raise totals by pressing a button.
"""
from datetime import datetime

from models import ACTIVE_RESPONSES, DonationResponse, db
from utils import allocation, chat, channels
from utils.notifications import notify_account, notify_donor


class ClaimError(Exception):
    pass


def claim_donation(donor, response_id):
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.donor_id != donor.id:
        raise ClaimError("That offer was not found.")
    if resp.response_status not in ACTIVE_RESPONSES:
        raise ClaimError("This offer is no longer open, so it cannot be claimed.")
    if resp.donor_claimed_at and not resp.claim_disputed_at:
        raise ClaimError("You already told the hospital. Please wait for them to check.")
    if resp.claim_disputed_at:
        raise ClaimError("The hospital could not find a donation record. Please speak to the hospital directly.")
    resp.donor_claimed_at = datetime.utcnow()
    chat.add_event(resp, "The donor says they have donated. The hospital will check and confirm.")
    notify_account("hospital", resp.request.hospital_id,
                   f"A donor says they donated for request #{resp.request_id}. Please check and confirm.",
                   resp.request_id, dedupe_key=f"claim:{resp.id}", commit=False)
    channels.alert_account("hospital", resp.request.hospital_id,
                           f"A donor says they donated for request #{resp.request_id}.", f"claim:{resp.id}", "Check a donation")
    allocation.audit("donor", donor.id, "donation.claimed", "response", resp.id)
    db.session.commit()
    return resp


def dispute_claim(hospital, response_id, note):
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.request.hospital_id != hospital.id:
        raise ClaimError("That offer was not found.")
    if not resp.donor_claimed_at or resp.claim_disputed_at:
        raise ClaimError("There is no open claim on this offer.")
    if resp.response_status not in ACTIVE_RESPONSES:
        raise ClaimError("This offer is already closed.")
    resp.claim_disputed_at = datetime.utcnow()
    resp.claim_note = (note or "").strip()[:200] or "No donation record was found."
    chat.add_event(resp, "The hospital could not find a donation record for this offer yet.")
    notify_donor(resp.donor_id, f"The hospital could not confirm your donation for request #{resp.request_id}. Open your responses for details.",
                 resp.request_id, dedupe_key=f"dispute:{resp.id}", commit=False)
    allocation.audit("hospital", hospital.id, "donation.claim_disputed", "response", resp.id)
    db.session.commit()
    return resp


def waiting_for_hospital(hospital_id):
    """Offers where the donor says they donated and the hospital has not decided yet."""
    from models import BloodRequest
    return (DonationResponse.query.join(BloodRequest, DonationResponse.request_id == BloodRequest.id)
            .filter(BloodRequest.hospital_id == hospital_id, DonationResponse.donor_claimed_at.isnot(None),
                    DonationResponse.claim_disputed_at.is_(None),
                    DonationResponse.response_status.in_(ACTIVE_RESPONSES))
            .order_by(DonationResponse.donor_claimed_at).all())

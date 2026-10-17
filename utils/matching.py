"""Blood group compatibility and donor matching (rule-based, not machine learning).

SCOPE: the table below is ABO/Rh compatibility for RED CELLS / whole blood.
Plasma and platelets follow different rules and are NOT modelled here.
A match is only a shortlist: the hospital must do screening, testing and
crossmatching before any transfusion.

Pipeline
  1. HARD filters (never overridden by score): compatible group, active account,
     marked available, interval since last donation, not deferred by a hospital,
     has not already responded.
  2. SCORE (transparent, configurable in config.MATCH_WEIGHTS) only orders the
     donors that passed step 1. With no GPS data, proximity is city-level.
"""
from models import Donor, db

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]

# Who a donor of a given blood group can donate WHOLE BLOOD to.
# O- is the universal donor, AB+ the universal recipient.
CAN_DONATE_TO = {
    "O-":  ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"],
    "O+":  ["O+", "A+", "B+", "AB+"],
    "A-":  ["A-", "A+", "AB-", "AB+"],
    "A+":  ["A+", "AB+"],
    "B-":  ["B-", "B+", "AB-", "AB+"],
    "B+":  ["B+", "AB+"],
    "AB-": ["AB-", "AB+"],
    "AB+": ["AB+"],
}


def can_donate(donor_group, recipient_group):
    """True if `donor_group` blood may be transfused into `recipient_group`."""
    return recipient_group in CAN_DONATE_TO.get(donor_group, [])


def compatible_donor_groups(recipient_group):
    """All donor blood groups that can supply `recipient_group`.

    Built by inverting CAN_DONATE_TO, so the two directions can never
    disagree with each other.
    """
    return [g for g, targets in CAN_DONATE_TO.items() if recipient_group in targets]


from collections import namedtuple

Match = namedtuple("Match", "donor score reasons")


def rank_donors(blood_request, only_available=True):
    """Return ``Match(donor, score, reasons)`` tuples, best first."""
    from datetime import date
    from flask import current_app
    from models import ACTIVE_RESPONSES, DonationResponse

    weights = current_app.config["MATCH_WEIGHTS"]
    groups = compatible_donor_groups(blood_request.blood_group_required)
    query = Donor.query.filter(Donor.blood_group.in_(groups), Donor.is_active.is_(True))
    if only_available:
        query = query.filter(Donor.availability == "Available")

    responded = {
        did for (did,) in db.session.query(DonationResponse.donor_id).filter(
            DonationResponse.request_id == blood_request.id,
            DonationResponse.response_status.in_(ACTIVE_RESPONSES + ("Donation Completed",)),
        )
    }
    location = (blood_request.location or "").lower()
    hospital = getattr(blood_request, "hospital", None)
    hospital_city = (hospital.city or "").lower() if hospital else ""

    matches = []
    for donor in query.all():
        if donor.id in responded or not donor.is_matchable:     # hard filters
            continue
        score, reasons = 0, ["Blood group is compatible"]
        city = (donor.city or "").lower()
        if city and (city in location or city == hospital_city):
            score += weights["same_city"]; reasons.append("Same city as the hospital")
        else:
            reasons.append("Different city")
        if donor.blood_group == blood_request.blood_group_required:
            score += weights["exact_group"]; reasons.append("Exact blood group")
        if donor.last_donation_date is None:
            score += weights["never_donated_or_long_rest"]; reasons.append("No donation on record")
        matches.append(Match(donor, score, reasons))
    matches.sort(key=lambda m: (-m.score, m.donor.name.lower()))
    return matches


def find_matching_donors(blood_request, limit=None, only_available=True):
    """Donors who can help with this request, best match first."""
    donors = [m.donor for m in rank_donors(blood_request, only_available)]
    return donors[:limit] if limit else donors


def requests_for_donor(donor, base_query):
    """Filter a BloodRequest query down to open requests this donor can answer."""
    from models import OPEN_STATUSES, BloodRequest

    recipients = CAN_DONATE_TO.get(donor.blood_group, [])
    return base_query.filter(
        BloodRequest.status.in_(OPEN_STATUSES),
        BloodRequest.blood_group_required.in_(recipients),
    ).order_by(BloodRequest.created_at.desc())

"""Blood group compatibility and donor matching.

The matching engine answers one question: given an approved blood request,
which registered donors can actually help?
"""
from models import Donor

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


def find_matching_donors(blood_request, limit=None, only_available=True):
    """Return donors who can help with this request, best match first.

    Ranking:
      1. exact blood group match in the same city
      2. compatible blood group in the same city
      3. exact blood group elsewhere
      4. compatible blood group elsewhere
    """
    groups = compatible_donor_groups(blood_request.blood_group_required)

    query = Donor.query.filter(Donor.blood_group.in_(groups), Donor.is_active.is_(True))
    if only_available:
        query = query.filter(Donor.availability == "Available")

    candidates = query.all()

    # Eligibility is a computed value (depends on today's date), so it is
    # filtered in Python rather than in SQL.
    candidates = [d for d in candidates if d.is_eligible]

    location = (blood_request.location or "").lower()
    hospital = getattr(blood_request, "hospital", None)
    hospital_city = (hospital.city or "").lower() if hospital else ""

    def sort_key(donor):
        # "Near" means the donor's city appears in the typed location OR is
        # the city of the hospital the request is attached to.
        city = (donor.city or "").lower()
        same_city = bool(city) and (city in location or city == hospital_city)
        exact = donor.blood_group == blood_request.blood_group_required
        # lower tuple sorts first
        return (0 if same_city else 1, 0 if exact else 1, donor.name.lower())

    candidates.sort(key=sort_key)
    return candidates[:limit] if limit else candidates


def requests_for_donor(donor, base_query):
    """Filter a BloodRequest query down to requests this donor can answer."""
    from models import BloodRequest, STATUS_APPROVED

    recipients = CAN_DONATE_TO.get(donor.blood_group, [])
    return base_query.filter(
        BloodRequest.status == STATUS_APPROVED,
        BloodRequest.blood_group_required.in_(recipients),
    ).order_by(BloodRequest.created_at.desc())

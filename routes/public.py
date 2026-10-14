"""Public pages: home, about, how it works, find blood, emergency, contact."""
from collections import Counter

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from models import (STATUS_APPROVED, STATUS_FULFILLED, BloodRequest, Donor,
                    Hospital, Patient)
from utils.auth import current_user, remember_next
from utils.matching import BLOOD_GROUPS, CAN_DONATE_TO, compatible_donor_groups

public_bp = Blueprint("public", __name__)


def site_statistics():
    return {
        "donors": Donor.query.filter_by(is_active=True).count(),
        "active_requests": BloodRequest.query.filter_by(status=STATUS_APPROVED).count(),
        "hospitals": Hospital.query.filter_by(is_active=True, is_verified=True).count(),
        "donations": BloodRequest.query.filter_by(status=STATUS_FULFILLED).count(),
        "patients": Patient.query.count(),
    }


@public_bp.route("/")
def index():
    urgent = (
        BloodRequest.query.filter_by(status=STATUS_APPROVED)
        .order_by(BloodRequest.created_at.desc())
        .limit(6)
        .all()
    )
    have = _ready_donors()
    return render_template(
        "index.html", stats=site_statistics(), requests=urgent,
        blood_groups=BLOOD_GROUPS, counts=_availability_counts(have),
        available_now=sum(have.values()), can_donate_to=CAN_DONATE_TO,
    )


@public_bp.route("/about")
def about():
    return render_template("about.html")


@public_bp.route("/how-it-works")
def how_it_works():
    return render_template("how_it_works.html")


class Page:
    """Minimal pagination object with the same attributes as Flask-SQLAlchemy's
    (items, page, pages), used because donors are ranked in Python first."""

    def __init__(self, all_items, page, per_page):
        self.total = len(all_items)
        self.pages = max(1, -(-self.total // per_page))
        self.page = min(max(page, 1), self.pages)
        start = (self.page - 1) * per_page
        self.items = all_items[start:start + per_page]


def _ready_donors():
    """Count of donors who are active, available and eligible, per group."""
    return Counter(
        d.blood_group for d in Donor.query.filter_by(is_active=True, availability="Available").all()
        if d.is_eligible
    )


def _availability_counts(have=None):
    """For each blood group NEEDED, how many donors could help right now.
    Only aggregate numbers are returned, so nothing personal is exposed to
    visitors who have not logged in."""
    have = have if have is not None else _ready_donors()
    return {g: sum(have.get(x, 0) for x in compatible_donor_groups(g)) for g in BLOOD_GROUPS}


@public_bp.route("/find-blood")
def find_blood():
    """Step 1: choose the blood group that is NEEDED.
    Step 2: visitors who are not logged in are asked to log in / register.
    Step 3: logged-in users see every donor who can safely give that group.
    """
    needed = request.args.get("blood_group", "")

    # ---- Step 1: no group chosen yet -> show the picker ------------------
    if needed not in BLOOD_GROUPS and needed != "all":
        return render_template(
            "find_blood.html", stage="pick", blood_groups=BLOOD_GROUPS,
            counts=_availability_counts(),
            accepts={g: len(compatible_donor_groups(g)) for g in BLOOD_GROUPS},
        )

    # ---- Step 2: login gate ---------------------------------------------
    user = current_user()
    if user is None:
        remember_next(request.full_path.rstrip("?"))
        return render_template(
            "auth/gate.html", needed=needed, blood_groups=BLOOD_GROUPS,
            givers=compatible_donor_groups(needed) if needed != "all" else BLOOD_GROUPS,
        )

    # ---- Step 3: results (compatible donors, best match first) ------------
    match = request.args.get("match", "compatible")
    city = request.args.get("city", "").strip()
    availability = request.args.get("availability", "Available")

    if needed == "all":
        groups = list(BLOOD_GROUPS)
    elif match == "exact":
        groups = [needed]
    else:
        groups = compatible_donor_groups(needed)

    query = Donor.query.filter(Donor.is_active.is_(True), Donor.blood_group.in_(groups))
    if city:
        query = query.filter(Donor.city.ilike(f"%{city}%"))
    if availability in ("Available", "Not Available"):
        query = query.filter(Donor.availability == availability)
    donors = query.all()

    my_city = (getattr(user, "city", "") or "").lower()

    def rank(d):
        return (
            0 if d.is_matchable else 1,                     # can help right now
            0 if my_city and (d.city or "").lower() == my_city else 1,   # nearest
            0 if d.blood_group == needed else 1,            # exact group first
            (d.city or "").lower(), d.name.lower(),
        )

    donors.sort(key=rank)
    page = Page(donors, request.args.get("page", 1, type=int), 12)
    cities = sorted({c for (c,) in Donor.query.with_entities(Donor.city).distinct() if c})

    show_contact = (
        current_app.config["SHOW_DONOR_CONTACT_TO_REQUESTERS"]
        and user.role in ("patient", "hospital", "admin")
    )
    return render_template(
        "find_blood.html", stage="results", donors=page, needed=needed,
        blood_groups=BLOOD_GROUPS, cities=cities, givers=groups,
        show_contact=show_contact, my_city=getattr(user, "city", ""),
        filters={"blood_group": needed, "city": city, "availability": availability,
                 "match": match},
    )


@public_bp.route("/emergency")
def emergency():
    blood_group = request.args.get("blood_group", "")
    city = request.args.get("city", "").strip()
    urgency = request.args.get("urgency", "")

    query = BloodRequest.query.filter_by(status=STATUS_APPROVED)
    if blood_group in BLOOD_GROUPS:
        query = query.filter_by(blood_group_required=blood_group)
    if city:
        query = query.filter(BloodRequest.location.ilike(f"%{city}%"))
    if urgency in ("Normal", "Urgent", "Critical"):
        query = query.filter_by(urgency=urgency)

    page = request.args.get("page", 1, type=int)
    requests_page = query.order_by(BloodRequest.created_at.desc()).paginate(
        page=page, per_page=9, error_out=False
    )
    return render_template(
        "emergency.html", requests=requests_page, blood_groups=BLOOD_GROUPS,
        filters={"blood_group": blood_group, "city": city, "urgency": urgency},
    )


@public_bp.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        message = request.form.get("message", "").strip()
        if not name or not message:
            flash("Please fill in your name and message.", "danger")
        else:
            # A university project keeps this simple: the message is
            # acknowledged rather than emailed through a paid service.
            flash("Thanks, your message has been received. We will reply by email.", "success")
            return redirect(url_for("public.contact"))
    return render_template("contact.html")

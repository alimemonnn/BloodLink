"""Donor dashboard, profile, request feed, responses and history."""
from datetime import date
from urllib.parse import urlparse

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from models import (RESP_COMPLETED, BloodRequest, DonationResponse,
                    Notification, db)
from utils import allocation
from utils.auth import current_user, role_required
from utils.matching import BLOOD_GROUPS, requests_for_donor
from utils.notifications import mark_all_read, notify_donor
from utils.validators import (checked, parse_date, validate_donor_form,
                              validate_password)

donor_bp = Blueprint("donor", __name__, url_prefix="/donor")


@donor_bp.route("/dashboard")
@role_required("donor")
def dashboard():
    donor = current_user()
    donor.refresh_eligibility()
    db.session.commit()

    matching = requests_for_donor(donor, BloodRequest.query).limit(5).all()
    responses = DonationResponse.query.filter_by(donor_id=donor.id).all()
    notifications = (
        Notification.query.filter_by(donor_id=donor.id)
        .order_by(Notification.created_at.desc())
        .limit(5)
        .all()
    )
    stats = {
        "responses": len(responses),
        "completed": sum(1 for r in responses if r.response_status == RESP_COMPLETED),
        "open_requests": requests_for_donor(donor, BloodRequest.query).count(),
        "unread": sum(1 for n in notifications if not n.is_read),
    }
    return render_template(
        "donor/dashboard.html", donor=donor, requests=matching,
        stats=stats, notifications=notifications,
    )


@donor_bp.route("/requests")
@role_required("donor")
def requests_feed():
    """Approved requests this donor's blood group can serve."""
    donor = current_user()
    query = requests_for_donor(donor, BloodRequest.query)

    city = request.args.get("city", "").strip()
    urgency = request.args.get("urgency", "")
    if city:
        query = query.filter(BloodRequest.location.ilike(f"%{city}%"))
    if urgency in ("Normal", "Urgent", "Critical"):
        query = query.filter(BloodRequest.urgency == urgency)

    page = request.args.get("page", 1, type=int)
    items = query.paginate(page=page, per_page=9, error_out=False)

    responded_ids = {
        r.request_id for r in DonationResponse.query.filter_by(donor_id=donor.id).all()
    }
    return render_template(
        "donor/requests.html", donor=donor, requests=items,
        responded_ids=responded_ids, filters={"city": city, "urgency": urgency},
    )


@donor_bp.route("/requests/<int:request_id>/respond", methods=["POST"])
@role_required("donor")
def respond(request_id):
    """Offer to help. The tick box is the donor's consent to share contact details."""
    donor = current_user()
    BloodRequest.query.get_or_404(request_id)
    try:
        allocation.pledge(donor, request_id, units=1,
                          consent_to_share=checked(request.form, "share_with_hospital"))
    except allocation.AllocationError as err:
        flash(str(err), "warning")
        return redirect(url_for("donor.requests_feed"))
    flash("Thank you. The hospital and patient can now see your name and phone number. "
          "Your offer is not a medical clearance: the hospital will confirm with you.", "success")
    return redirect(url_for("donor.history"))


@donor_bp.route("/history")
@role_required("donor")
def history():
    donor = current_user()
    responses = (
        DonationResponse.query.filter_by(donor_id=donor.id)
        .order_by(DonationResponse.response_date.desc())
        .all()
    )
    return render_template("donor/history.html", donor=donor, responses=responses)


@donor_bp.route("/history/<int:response_id>/cancel", methods=["POST"])
@role_required("donor")
def cancel_response(response_id):
    """Donors can withdraw an offer. Only a hospital can record a completed donation."""
    donor = current_user()
    try:
        allocation.cancel_response(response_id, "donor", donor.id)
        flash("Your offer was cancelled.", "info")
    except allocation.AllocationError as err:
        flash(str(err), "warning")
    return redirect(url_for("donor.history"))


@donor_bp.route("/availability", methods=["POST"])
@role_required("donor")
def toggle_availability():
    donor = current_user()
    donor.availability = "Not Available" if donor.availability == "Available" else "Available"
    db.session.commit()
    flash(f"You are now marked as {donor.availability}.", "info")
    return redirect(_same_site_referrer() or url_for("donor.dashboard"))


def _same_site_referrer():
    """Go back to the page the click came from, but only if it is on this
    site (a forged Referer header must not redirect users elsewhere)."""
    ref = urlparse(request.referrer or "")
    if ref.netloc == request.host and ref.path.startswith("/"):
        return ref.path + (f"?{ref.query}" if ref.query else "")
    return None


@donor_bp.route("/profile", methods=["GET", "POST"])
@role_required("donor")
def profile():
    donor = current_user()
    if request.method == "POST":
        form = request.form.to_dict()
        form["email"] = donor.email          # email is not editable
        errors = validate_donor_form(form, require_password=False)
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            donor.name = form["name"].strip()
            donor.phone = form["phone"].strip()
            donor.blood_group = form["blood_group"]
            donor.city = form["city"].strip()
            donor.area = form.get("area", "").strip()
            donor.last_donation_date = parse_date(form.get("last_donation_date"))
            donor.availability = form.get("availability", donor.availability)
            donor.refresh_eligibility()
            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("donor.profile"))
    return render_template("donor/profile.html", donor=donor, blood_groups=BLOOD_GROUPS)


@donor_bp.route("/password", methods=["POST"])
@role_required("donor")
def change_password():
    donor = current_user()
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if not donor.check_password(current):
        flash("Your current password is incorrect.", "danger")
        return redirect(url_for("donor.profile"))

    errors = validate_password(new, confirm)
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("donor.profile"))

    donor.set_password(new)
    db.session.commit()
    flash("Password changed.", "success")
    return redirect(url_for("donor.profile"))


@donor_bp.route("/notifications")
@role_required("donor")
def notifications():
    donor = current_user()
    items = (
        Notification.query.filter_by(donor_id=donor.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    mark_all_read(donor.id)
    return render_template("donor/notifications.html", donor=donor, notifications=items)

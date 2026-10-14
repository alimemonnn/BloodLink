"""Hospital dashboard: verify, approve, reject and fulfil blood requests."""
from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from models import (STATUS_APPROVED, STATUS_FULFILLED, STATUS_PENDING,
                    STATUS_REJECTED, BloodRequest, db)
from utils.auth import current_user, role_required
from utils.matching import find_matching_donors
from utils.notifications import notify_matching_donors
from utils.validators import validate_hospital_form, validate_password

hospital_bp = Blueprint("hospital", __name__, url_prefix="/hospital")


@hospital_bp.route("/dashboard")
@role_required("hospital")
def dashboard():
    hospital = current_user()
    requests_list = BloodRequest.query.filter_by(hospital_id=hospital.id).all()
    stats = {
        "pending": sum(1 for r in requests_list if r.status == STATUS_PENDING),
        "approved": sum(1 for r in requests_list if r.status == STATUS_APPROVED),
        "fulfilled": sum(1 for r in requests_list if r.status == STATUS_FULFILLED),
        "critical": sum(
            1 for r in requests_list
            if r.urgency == "Critical" and r.status in (STATUS_PENDING, STATUS_APPROVED)
        ),
    }
    recent = (
        BloodRequest.query.filter_by(hospital_id=hospital.id)
        .order_by(BloodRequest.created_at.desc())
        .limit(6)
        .all()
    )
    return render_template(
        "hospital/dashboard.html", hospital=hospital, stats=stats, requests=recent
    )


@hospital_bp.route("/requests")
@role_required("hospital")
def requests_list():
    hospital = current_user()
    status = request.args.get("status", "")
    urgency = request.args.get("urgency", "")

    query = BloodRequest.query.filter_by(hospital_id=hospital.id)
    if status:
        query = query.filter_by(status=status)
    if urgency:
        query = query.filter_by(urgency=urgency)

    items = query.order_by(BloodRequest.created_at.desc()).all()
    return render_template(
        "hospital/requests.html", hospital=hospital, requests=items,
        status=status, urgency=urgency,
    )


def _own_request(request_id, hospital):
    blood_request = BloodRequest.query.get_or_404(request_id)
    if blood_request.hospital_id != hospital.id:
        return None
    return blood_request


@hospital_bp.route("/requests/<int:request_id>")
@role_required("hospital")
def request_detail(request_id):
    hospital = current_user()
    blood_request = _own_request(request_id, hospital)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))

    matches = (
        find_matching_donors(blood_request, limit=15)
        if blood_request.status == STATUS_APPROVED else []
    )
    return render_template(
        "hospital/request_detail.html", hospital=hospital,
        blood_request=blood_request, matches=matches,
    )


@hospital_bp.route("/requests/<int:request_id>/approve", methods=["POST"])
@role_required("hospital")
def approve(request_id):
    """Approving a request makes it visible to matching donors and sends
    in-app notifications to them."""
    hospital = current_user()
    blood_request = _own_request(request_id, hospital)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))

    if blood_request.status != STATUS_PENDING:
        flash("Only a pending request can be approved.", "warning")
        return redirect(url_for("hospital.request_detail", request_id=request_id))

    blood_request.status = STATUS_APPROVED
    blood_request.hospital_verified = True
    blood_request.hospital_notes = request.form.get("hospital_notes", "").strip()
    db.session.commit()

    notified = notify_matching_donors(blood_request)
    flash(f"Request approved. {notified} matching donors were notified.", "success")
    return redirect(url_for("hospital.request_detail", request_id=request_id))


@hospital_bp.route("/requests/<int:request_id>/reject", methods=["POST"])
@role_required("hospital")
def reject(request_id):
    hospital = current_user()
    blood_request = _own_request(request_id, hospital)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))

    if blood_request.status != STATUS_PENDING:
        flash("Only a pending request can be rejected.", "warning")
        return redirect(url_for("hospital.request_detail", request_id=request_id))

    blood_request.status = STATUS_REJECTED
    blood_request.hospital_verified = False
    blood_request.hospital_notes = request.form.get("hospital_notes", "").strip()
    db.session.commit()
    flash("Request rejected.", "info")
    return redirect(url_for("hospital.request_detail", request_id=request_id))


@hospital_bp.route("/requests/<int:request_id>/verify", methods=["POST"])
@role_required("hospital")
def verify(request_id):
    hospital = current_user()
    blood_request = _own_request(request_id, hospital)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))

    blood_request.hospital_verified = not blood_request.hospital_verified
    notes = request.form.get("hospital_notes", "").strip()
    if notes:
        blood_request.hospital_notes = notes
    db.session.commit()
    state = "Verified" if blood_request.hospital_verified else "Not Verified"
    flash(f"Request marked as {state}.", "success")
    return redirect(url_for("hospital.request_detail", request_id=request_id))


@hospital_bp.route("/requests/<int:request_id>/fulfill", methods=["POST"])
@role_required("hospital")
def fulfill(request_id):
    hospital = current_user()
    blood_request = _own_request(request_id, hospital)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))

    if blood_request.status != STATUS_APPROVED:
        flash("Only an approved request can be marked as fulfilled.", "warning")
    else:
        blood_request.status = STATUS_FULFILLED
        db.session.commit()
        flash("Request marked as fulfilled. Donors will no longer see it.", "success")
    return redirect(url_for("hospital.request_detail", request_id=request_id))


@hospital_bp.route("/profile", methods=["GET", "POST"])
@role_required("hospital")
def profile():
    hospital = current_user()
    if request.method == "POST":
        form = request.form.to_dict()
        form["email"] = hospital.email
        errors = validate_hospital_form(form, require_password=False)
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            hospital.hospital_name = form["hospital_name"].strip()
            hospital.phone = form["phone"].strip()
            hospital.address = form["address"].strip()
            hospital.city = form["city"].strip()
            db.session.commit()
            flash("Hospital profile updated.", "success")
            return redirect(url_for("hospital.profile"))
    return render_template("hospital/profile.html", hospital=hospital)


@hospital_bp.route("/password", methods=["POST"])
@role_required("hospital")
def change_password():
    hospital = current_user()
    if not hospital.check_password(request.form.get("current_password", "")):
        flash("Your current password is incorrect.", "danger")
        return redirect(url_for("hospital.profile"))
    errors = validate_password(
        request.form.get("new_password", ""), request.form.get("confirm_password", "")
    )
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("hospital.profile"))
    hospital.set_password(request.form["new_password"])
    db.session.commit()
    flash("Password changed.", "success")
    return redirect(url_for("hospital.profile"))

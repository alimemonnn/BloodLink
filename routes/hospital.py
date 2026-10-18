"""Hospital dashboard: verify, approve, reject and fulfil blood requests."""
from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)

from datetime import datetime

from models import (OPEN_STATUSES, STATUS_APPROVED, STATUS_FULFILLED,
                    STATUS_PARTIAL, STATUS_PENDING, STATUS_REJECTED,
                    BloodRequest, db)
from utils import allocation
from utils.auth import current_user, role_required
from utils.matching import rank_donors
from utils.notifications import (account_updates, notify_account,
                                 notify_matching_donors)
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
        "partial": sum(1 for r in requests_list if r.status == STATUS_PARTIAL),
        "fulfilled": sum(1 for r in requests_list if r.status == STATUS_FULFILLED),
        "outstanding_units": sum(r.units_remaining for r in requests_list
                                 if r.status in OPEN_STATUSES),
        "critical": sum(
            1 for r in requests_list
            if r.urgency == "Critical" and r.status in (STATUS_PENDING, STATUS_APPROVED, STATUS_PARTIAL)
        ),
    }
    recent = (
        BloodRequest.query.filter_by(hospital_id=hospital.id)
        .order_by(BloodRequest.created_at.desc())
        .limit(6)
        .all()
    )
    return render_template(
        "hospital/dashboard.html", hospital=hospital, stats=stats, requests=recent,
        updates=account_updates("hospital", hospital.id, mark_read=True),
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
        rank_donors(blood_request)[:15] if blood_request.status in OPEN_STATUSES else []
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
    blood_request.approved_at = datetime.utcnow()
    blood_request.hospital_verified = True
    blood_request.hospital_notes = request.form.get("hospital_notes", "").strip()
    notify_account("patient", blood_request.patient_id,
                   f"Request #{blood_request.id} was approved and is now visible to donors.",
                   blood_request.id, dedupe_key=f"approved:{blood_request.id}", commit=False)
    allocation.audit("hospital", hospital.id, "request.approve", "request", blood_request.id)
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
    notify_account("patient", blood_request.patient_id,
                   f"Request #{blood_request.id} was not approved by the hospital.",
                   blood_request.id, dedupe_key=f"rejected:{blood_request.id}", commit=False)
    allocation.audit("hospital", hospital.id, "request.reject", "request", blood_request.id)
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


def _back(request_id):
    return redirect(url_for("hospital.request_detail", request_id=request_id))


def _run(request_id, action, success, *args, **kwargs):
    """Run an allocation action for this hospital and flash the outcome."""
    hospital = current_user()
    if _own_request(request_id, hospital) is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))
    try:
        action(hospital, *args, **kwargs)
        flash(success, "success")
    except allocation.NotAuthorized:
        flash("Unauthorized access.", "danger")
    except allocation.AllocationError as err:
        flash(str(err), "warning")
    return _back(request_id)


@hospital_bp.route("/requests/<int:request_id>/responses/<int:response_id>/contact", methods=["POST"])
@role_required("hospital")
def contact_donor(request_id, response_id):
    return _run(request_id, allocation.mark_contacted, "Donor marked as contacted.", response_id)


@hospital_bp.route("/requests/<int:request_id>/responses/<int:response_id>/schedule", methods=["POST"])
@role_required("hospital")
def schedule_donor(request_id, response_id):
    try:
        when = datetime.strptime(request.form.get("appointment_at", ""), "%Y-%m-%dT%H:%M")
    except ValueError:
        when = None
    return _run(request_id, allocation.schedule_appointment, "Appointment scheduled.",
                response_id, when, request.form.get("note", "").strip())


@hospital_bp.route("/requests/<int:request_id>/responses/<int:response_id>/ineligible", methods=["POST"])
@role_required("hospital")
def donor_ineligible(request_id, response_id):
    return _run(request_id, allocation.mark_ineligible, "Donor recorded as ineligible.",
                response_id, request.form.get("note", "").strip(),
                request.form.get("deferral_days", 0))


@hospital_bp.route("/requests/<int:request_id>/responses/<int:response_id>/cancel", methods=["POST"])
@role_required("hospital")
def cancel_donor(request_id, response_id):
    hospital = current_user()
    return _run(request_id,
                lambda h, rid: allocation.cancel_response(rid, "hospital", h.id,
                                                           request.form.get("note", "").strip()),
                "Donor response cancelled.", response_id)


@hospital_bp.route("/requests/<int:request_id>/responses/<int:response_id>/confirm", methods=["POST"])
@role_required("hospital")
def confirm_donation(request_id, response_id):
    """Verify that this donor really gave blood. This is what counts units."""
    return _run(request_id, allocation.confirm_donation, "Donation verified and counted.",
                response_id, request.form.get("units") or None)


@hospital_bp.route("/requests/<int:request_id>/close", methods=["POST"])
@role_required("hospital")
def close(request_id):
    return _run(request_id,
                lambda h, rid: allocation.close_request(rid, "hospital", h.id,
                                                         request.form.get("reason", "")),
                "Request closed.", request_id)


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

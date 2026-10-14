"""Patient dashboard: post, track and manage blood requests."""
from datetime import datetime, timedelta

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from models import (STATUS_APPROVED, STATUS_EXPIRED, STATUS_FULFILLED,
                    STATUS_PENDING, STATUS_REJECTED, BloodRequest,
                    DonationResponse, Hospital, db)
from utils.auth import current_user, role_required
from utils.matching import BLOOD_GROUPS, find_matching_donors
from utils.validators import (URGENCY_LEVELS, validate_blood_request_form,
                              validate_password, validate_patient_form)

patient_bp = Blueprint("patient", __name__, url_prefix="/patient")


def _verified_hospitals():
    return (
        Hospital.query.filter_by(is_active=True, is_verified=True)
        .order_by(Hospital.hospital_name)
        .all()
    )


@patient_bp.route("/dashboard")
@role_required("patient")
def dashboard():
    patient = current_user()
    requests_list = (
        BloodRequest.query.filter_by(patient_id=patient.id)
        .order_by(BloodRequest.created_at.desc())
        .all()
    )
    stats = {
        "total": len(requests_list),
        "pending": sum(1 for r in requests_list if r.status == STATUS_PENDING),
        "approved": sum(1 for r in requests_list if r.status == STATUS_APPROVED),
        "fulfilled": sum(1 for r in requests_list if r.status == STATUS_FULFILLED),
        "responses": sum(r.response_count for r in requests_list),
    }
    return render_template(
        "patient/dashboard.html", patient=patient,
        requests=requests_list[:5], stats=stats,
    )


@patient_bp.route("/requests")
@role_required("patient")
def requests_list():
    patient = current_user()
    status = request.args.get("status", "")
    query = BloodRequest.query.filter_by(patient_id=patient.id)
    if status:
        query = query.filter_by(status=status)
    items = query.order_by(BloodRequest.created_at.desc()).all()
    return render_template(
        "patient/requests.html", patient=patient, requests=items, status=status,
        statuses=[STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
                  STATUS_FULFILLED, STATUS_EXPIRED],
    )


@patient_bp.route("/requests/new", methods=["GET", "POST"])
@role_required("patient")
def new_request():
    patient = current_user()
    form = {"patient_name": patient.name, "contact_number": patient.phone,
            "location": patient.city, "units_required": 1, "urgency": "Normal"}

    if request.method == "POST":
        form = request.form.to_dict()
        errors = validate_blood_request_form(form)
        hospital = Hospital.query.get(form.get("hospital_id") or 0)
        if hospital is None or not (hospital.is_active and hospital.is_verified):
            errors.append("Please select a valid hospital.")

        # Abuse prevention: a single account cannot flood the system.
        hour_ago = datetime.utcnow() - timedelta(hours=1)
        recent = BloodRequest.query.filter(
            BloodRequest.patient_id == patient.id, BloodRequest.created_at >= hour_ago
        ).count()
        if recent >= current_app.config["MAX_REQUESTS_PER_HOUR"]:
            errors.append("You have posted several requests in the last hour. "
                          "Please wait a little before posting another.")

        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            blood_request = BloodRequest(
                patient_id=patient.id,
                hospital_id=hospital.id,
                patient_name=form["patient_name"].strip(),
                blood_group_required=form["blood_group_required"],
                units_required=int(form["units_required"]),
                urgency=form["urgency"],
                location=form["location"].strip(),
                contact_number=form["contact_number"].strip(),
                description=form.get("description", "").strip(),
                status=STATUS_PENDING,   # donors cannot see it yet
            )
            db.session.add(blood_request)
            db.session.commit()
            flash(
                "Request submitted. It is now waiting for hospital approval and "
                "is not visible to donors yet.",
                "success",
            )
            return redirect(url_for("patient.request_detail", request_id=blood_request.id))

    return render_template(
        "patient/request_form.html", patient=patient, form=form,
        hospitals=_verified_hospitals(), blood_groups=BLOOD_GROUPS,
        urgency_levels=URGENCY_LEVELS, editing=False,
    )


def _owned_request(request_id, patient):
    blood_request = BloodRequest.query.get_or_404(request_id)
    if blood_request.patient_id != patient.id:
        return None
    return blood_request


@patient_bp.route("/requests/<int:request_id>")
@role_required("patient")
def request_detail(request_id):
    patient = current_user()
    blood_request = _owned_request(request_id, patient)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("patient.requests_list"))

    matches = (
        find_matching_donors(blood_request, limit=10)
        if blood_request.status == STATUS_APPROVED else []
    )
    return render_template(
        "patient/request_detail.html", patient=patient,
        blood_request=blood_request, matches=matches,
    )


@patient_bp.route("/requests/<int:request_id>/edit", methods=["GET", "POST"])
@role_required("patient")
def edit_request(request_id):
    patient = current_user()
    blood_request = _owned_request(request_id, patient)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("patient.requests_list"))

    # Once a hospital has acted on a request it becomes read-only.
    if not blood_request.is_editable:
        flash("A request cannot be edited after the hospital has reviewed it.", "warning")
        return redirect(url_for("patient.request_detail", request_id=request_id))

    if request.method == "POST":
        form = request.form.to_dict()
        errors = validate_blood_request_form(form)
        hospital = Hospital.query.get(form.get("hospital_id") or 0)
        if hospital is None or not (hospital.is_active and hospital.is_verified):
            errors.append("Please select a valid hospital.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            blood_request.hospital_id = hospital.id
            blood_request.patient_name = form["patient_name"].strip()
            blood_request.blood_group_required = form["blood_group_required"]
            blood_request.units_required = int(form["units_required"])
            blood_request.urgency = form["urgency"]
            blood_request.location = form["location"].strip()
            blood_request.contact_number = form["contact_number"].strip()
            blood_request.description = form.get("description", "").strip()
            db.session.commit()
            flash("Request updated.", "success")
            return redirect(url_for("patient.request_detail", request_id=request_id))

    form = {
        "patient_name": blood_request.patient_name,
        "blood_group_required": blood_request.blood_group_required,
        "hospital_id": blood_request.hospital_id,
        "units_required": blood_request.units_required,
        "urgency": blood_request.urgency,
        "location": blood_request.location,
        "contact_number": blood_request.contact_number,
        "description": blood_request.description,
    }
    return render_template(
        "patient/request_form.html", patient=patient, form=form,
        hospitals=_verified_hospitals(), blood_groups=BLOOD_GROUPS,
        urgency_levels=URGENCY_LEVELS, editing=True, blood_request=blood_request,
    )


@patient_bp.route("/requests/<int:request_id>/fulfill", methods=["POST"])
@role_required("patient")
def mark_fulfilled(request_id):
    patient = current_user()
    blood_request = _owned_request(request_id, patient)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("patient.requests_list"))

    if blood_request.status != STATUS_APPROVED:
        flash("Only an approved request can be marked as fulfilled.", "warning")
    elif blood_request.responses:
        flash(
            "This request has donor responses recorded. Please confirm receipt "
            "against the specific donor who actually gave blood, so their "
            "90-day donation cooldown starts correctly.",
            "warning",
        )
    else:
        blood_request.status = STATUS_FULFILLED
        db.session.commit()
        flash("Request marked as fulfilled. Donors will no longer see it.", "success")
    return redirect(url_for("patient.request_detail", request_id=request_id))


@patient_bp.route("/requests/<int:request_id>/confirm-donor/<int:response_id>", methods=["POST"])
@role_required("patient")
def confirm_donor(request_id, response_id):
    """The patient confirms they actually received blood from this donor.

    This is the single action that ties the whole loop together:
    - the request is closed (Fulfilled) so it disappears from other donors,
    - this donor's response is marked "Donation Completed",
    - the donor's last_donation_date is set to today, which automatically
      starts their 90-day cooldown (Donor.is_eligible is computed from this,
      so no separate "deactivate" step is needed), and
    - admins can see exactly which donor fulfilled the request, on the
      request's donor-responses table.
    """
    patient = current_user()
    blood_request = _owned_request(request_id, patient)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("patient.requests_list"))

    response = DonationResponse.query.get_or_404(response_id)
    if response.request_id != blood_request.id:
        flash("That response does not belong to this request.", "danger")
        return redirect(url_for("patient.request_detail", request_id=request_id))

    if blood_request.status not in (STATUS_APPROVED, STATUS_FULFILLED):
        flash("Only an approved request can be confirmed as received.", "warning")
        return redirect(url_for("patient.request_detail", request_id=request_id))

    if response.response_status == "Donation Completed":
        flash("This donor is already recorded as having donated.", "info")
        return redirect(url_for("patient.request_detail", request_id=request_id))

    today = datetime.utcnow().date()
    response.response_status = "Donation Completed"
    response.donation_date = today

    donor = response.donor
    donor.last_donation_date = today
    donor.refresh_eligibility()

    blood_request.status = STATUS_FULFILLED

    db.session.commit()
    flash(
        f"Thank you for confirming. {donor.name} is recorded as your donor and "
        f"will not be matched again until {donor.next_eligible_date.strftime('%d %b %Y')}.",
        "success",
    )
    return redirect(url_for("patient.request_detail", request_id=request_id))


@patient_bp.route("/requests/<int:request_id>/cancel", methods=["POST"])
@role_required("patient")
def cancel_request(request_id):
    patient = current_user()
    blood_request = _owned_request(request_id, patient)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("patient.requests_list"))

    db.session.delete(blood_request)
    db.session.commit()
    flash("Request cancelled.", "info")
    return redirect(url_for("patient.requests_list"))


@patient_bp.route("/profile", methods=["GET", "POST"])
@role_required("patient")
def profile():
    patient = current_user()
    if request.method == "POST":
        form = request.form.to_dict()
        form["email"] = patient.email
        errors = validate_patient_form(form, require_password=False)
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            patient.name = form["name"].strip()
            patient.phone = form["phone"].strip()
            patient.city = form["city"].strip()
            patient.address = form.get("address", "").strip()
            db.session.commit()
            flash("Profile updated.", "success")
            return redirect(url_for("patient.profile"))
    return render_template("patient/profile.html", patient=patient)


@patient_bp.route("/password", methods=["POST"])
@role_required("patient")
def change_password():
    patient = current_user()
    if not patient.check_password(request.form.get("current_password", "")):
        flash("Your current password is incorrect.", "danger")
        return redirect(url_for("patient.profile"))
    errors = validate_password(
        request.form.get("new_password", ""), request.form.get("confirm_password", "")
    )
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(url_for("patient.profile"))
    patient.set_password(request.form["new_password"])
    db.session.commit()
    flash("Password changed.", "success")
    return redirect(url_for("patient.profile"))

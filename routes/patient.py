"""Patient dashboard: post, track and manage blood requests."""
from datetime import datetime, timedelta

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from models import (ALL_STATUSES, LIVE_STATUSES, OPEN_STATUSES, STATUS_APPROVED,
                    STATUS_FULFILLED, STATUS_PARTIAL, STATUS_PENDING,
                    BloodRequest, Hospital, db)
from utils import allocation
from utils.auth import current_user, role_required
from utils.matching import BLOOD_GROUPS
from utils.notifications import account_updates
from utils.validators import (URGENCY_LEVELS, checked, validate_blood_request_form,
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
        "approved": sum(1 for r in requests_list if r.status in (STATUS_APPROVED, STATUS_PARTIAL)),
        "outstanding_units": sum(r.units_remaining for r in requests_list if r.status in OPEN_STATUSES),
        "fulfilled": sum(1 for r in requests_list if r.status == STATUS_FULFILLED),
        "responses": sum(r.response_count for r in requests_list),
    }
    return render_template(
        "patient/dashboard.html", patient=patient,
        requests=requests_list[:5], stats=stats,
        updates=account_updates("patient", patient.id, mark_read=True),
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
        statuses=ALL_STATUSES,
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
            # A double-click must not create two identical requests.
            duplicate = BloodRequest.query.filter(
                BloodRequest.patient_id == patient.id, BloodRequest.hospital_id == hospital.id,
                BloodRequest.blood_group_required == form["blood_group_required"],
                BloodRequest.patient_name == form["patient_name"].strip(),
                BloodRequest.units_required == int(form["units_required"]),
                BloodRequest.status.in_(LIVE_STATUSES),
                BloodRequest.created_at >= datetime.utcnow() - timedelta(minutes=2)).first()
            if duplicate:
                flash("This request was already submitted.", "info")
                return redirect(url_for("patient.request_detail", request_id=duplicate.id))
            blood_request = BloodRequest(
                guardian_confirmed_at=datetime.utcnow() if checked(form, "patient_is_minor") else None,
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

    return render_template(
        "patient/request_detail.html", patient=patient, blood_request=blood_request,
        updates=account_updates("patient", patient.id, limit=5),
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


@patient_bp.route("/requests/<int:request_id>/cancel", methods=["POST"])
@role_required("patient")
def cancel_request(request_id):
    """Cancel keeps the record (history) and tells any donors who had offered."""
    patient = current_user()
    blood_request = _owned_request(request_id, patient)
    if blood_request is None:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("patient.requests_list"))
    try:
        allocation.close_request(request_id, "patient", patient.id,
                                 request.form.get("reason", "").strip())
        flash("Request cancelled.", "info")
    except allocation.AllocationError as err:
        flash(str(err), "warning")
    return redirect(url_for("patient.request_detail", request_id=request_id))


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

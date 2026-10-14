"""Admin panel: manage donors, patients, hospitals, requests and analytics."""
from collections import Counter
from datetime import datetime

from flask import (Blueprint, flash, redirect, render_template, request,
                   url_for)
from sqlalchemy import func

from models import (STATUS_APPROVED, STATUS_EXPIRED, STATUS_FULFILLED,
                    STATUS_PENDING, STATUS_REJECTED, Admin, BloodRequest,
                    DonationResponse, Donor, Hospital, Patient, db)
from utils.auth import current_user, role_required
from utils.matching import BLOOD_GROUPS, find_matching_donors
from utils.pagination import paginate_list
from utils.validators import (parse_date, validate_donor_form,
                              validate_hospital_form, validate_patient_form)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

PER_PAGE = 10


@admin_bp.route("/dashboard")
@role_required("admin")
def dashboard():
    stats = {
        "donors": Donor.query.count(),
        "patients": Patient.query.count(),
        "hospitals": Hospital.query.count(),
        "requests": BloodRequest.query.count(),
        "pending": BloodRequest.query.filter_by(status=STATUS_PENDING).count(),
        "approved": BloodRequest.query.filter_by(status=STATUS_APPROVED).count(),
        "fulfilled": BloodRequest.query.filter_by(status=STATUS_FULFILLED).count(),
        "expired": BloodRequest.query.filter_by(status=STATUS_EXPIRED).count(),
        "rejected": BloodRequest.query.filter_by(status=STATUS_REJECTED).count(),
        "responses": DonationResponse.query.count(),
        "unverified_hospitals": Hospital.query.filter_by(is_verified=False).count(),
    }
    stats["total_users"] = stats["donors"] + stats["patients"] + stats["hospitals"]

    # Donor counts per blood group, for the dashboard chart
    group_counts = {g: 0 for g in BLOOD_GROUPS}
    for group, count in db.session.query(Donor.blood_group, func.count(Donor.id)).group_by(
        Donor.blood_group
    ):
        group_counts[group] = count

    recent = BloodRequest.query.order_by(BloodRequest.created_at.desc()).limit(8).all()
    recent_users = _combined_users()[:6]
    return render_template(
        "admin/dashboard.html", stats=stats, group_counts=group_counts, requests=recent,
        recent_users=recent_users,
    )


# ----------------------------------------------------------------------
# All registered users (donors + patients + hospitals + admins)
# ----------------------------------------------------------------------
def _combined_users():
    """One row per account across every role, newest registration first.

    Never includes password_hash or any password data -- passwords are
    one-way hashed and cannot be shown even if we wanted to.
    """
    rows = []
    for d in Donor.query.all():
        rows.append({
            "id": d.id, "role": "donor", "role_label": "Donor", "name": d.name,
            "email": d.email, "phone": d.phone, "city": d.city,
            "created_at": d.created_at, "last_login_at": d.last_login_at,
            "is_active": d.is_active, "extra": d.blood_group,
            "detail_url": url_for("admin.donor_detail", donor_id=d.id),
        })
    for p in Patient.query.all():
        rows.append({
            "id": p.id, "role": "patient", "role_label": "Patient", "name": p.name,
            "email": p.email, "phone": p.phone, "city": p.city,
            "created_at": p.created_at, "last_login_at": p.last_login_at,
            "is_active": p.is_active, "extra": None,
            "detail_url": url_for("admin.patient_detail", patient_id=p.id),
        })
    for h in Hospital.query.all():
        rows.append({
            "id": h.id, "role": "hospital", "role_label": "Hospital", "name": h.hospital_name,
            "email": h.email, "phone": h.phone, "city": h.city,
            "created_at": h.created_at, "last_login_at": h.last_login_at,
            "is_active": h.is_active, "extra": "Verified" if h.is_verified else "Unverified",
            "detail_url": url_for("admin.hospital_detail", hospital_id=h.id),
        })
    for a in Admin.query.all():
        rows.append({
            "id": a.id, "role": "admin", "role_label": "Admin", "name": a.name,
            "email": a.email, "phone": None, "city": None,
            "created_at": a.created_at, "last_login_at": a.last_login_at,
            "is_active": True, "extra": None, "detail_url": None,
        })
    rows.sort(key=lambda r: r["created_at"] or datetime.min, reverse=True)
    return rows


@admin_bp.route("/users")
@role_required("admin")
def users():
    role = request.args.get("role", "")
    q = request.args.get("q", "").strip().lower()

    rows = _combined_users()
    if role in ("donor", "patient", "hospital", "admin"):
        rows = [r for r in rows if r["role"] == role]
    if q:
        rows = [r for r in rows if q in r["name"].lower() or q in r["email"].lower()]

    page = request.args.get("page", 1, type=int)
    items = paginate_list(rows, page, PER_PAGE)
    return render_template(
        "admin/users.html", users=items, filters={"role": role, "q": q},
        total_count=len(_combined_users()),
    )


# ----------------------------------------------------------------------
# Donors
# ----------------------------------------------------------------------
@admin_bp.route("/donors")
@role_required("admin")
def donors():
    name = request.args.get("name", "").strip()
    blood_group = request.args.get("blood_group", "")
    city = request.args.get("city", "").strip()
    availability = request.args.get("availability", "")

    query = Donor.query
    if name:
        query = query.filter(Donor.name.ilike(f"%{name}%"))
    if blood_group in BLOOD_GROUPS:
        query = query.filter_by(blood_group=blood_group)
    if city:
        query = query.filter(Donor.city.ilike(f"%{city}%"))
    if availability:
        query = query.filter_by(availability=availability)

    page = request.args.get("page", 1, type=int)
    items = query.order_by(Donor.created_at.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False
    )
    return render_template(
        "admin/donors.html", donors=items, blood_groups=BLOOD_GROUPS,
        filters={"name": name, "blood_group": blood_group, "city": city,
                 "availability": availability},
    )


@admin_bp.route("/donors/<int:donor_id>", methods=["GET", "POST"])
@role_required("admin")
def donor_detail(donor_id):
    donor = Donor.query.get_or_404(donor_id)
    if request.method == "POST":
        form = request.form.to_dict()
        form["email"] = donor.email
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
            flash("Donor updated.", "success")
            return redirect(url_for("admin.donor_detail", donor_id=donor.id))
    return render_template("admin/donor_detail.html", donor=donor, blood_groups=BLOOD_GROUPS)


@admin_bp.route("/donors/<int:donor_id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_donor(donor_id):
    donor = Donor.query.get_or_404(donor_id)
    donor.is_active = not donor.is_active
    db.session.commit()
    flash(f"Donor account {'activated' if donor.is_active else 'deactivated'}.", "info")
    return redirect(request.referrer or url_for("admin.donors"))


@admin_bp.route("/donors/<int:donor_id>/delete", methods=["POST"])
@role_required("admin")
def delete_donor(donor_id):
    donor = Donor.query.get_or_404(donor_id)
    db.session.delete(donor)
    db.session.commit()
    flash("Donor account deleted.", "info")
    return redirect(url_for("admin.donors"))


# ----------------------------------------------------------------------
# Patients
# ----------------------------------------------------------------------
@admin_bp.route("/patients")
@role_required("admin")
def patients():
    name = request.args.get("name", "").strip()
    city = request.args.get("city", "").strip()
    query = Patient.query
    if name:
        query = query.filter(Patient.name.ilike(f"%{name}%"))
    if city:
        query = query.filter(Patient.city.ilike(f"%{city}%"))
    page = request.args.get("page", 1, type=int)
    items = query.order_by(Patient.created_at.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False
    )
    return render_template("admin/patients.html", patients=items,
                           filters={"name": name, "city": city})


@admin_bp.route("/patients/<int:patient_id>", methods=["GET", "POST"])
@role_required("admin")
def patient_detail(patient_id):
    patient = Patient.query.get_or_404(patient_id)
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
            flash("Patient updated.", "success")
            return redirect(url_for("admin.patient_detail", patient_id=patient.id))
    return render_template("admin/patient_detail.html", patient=patient)


@admin_bp.route("/patients/<int:patient_id>/delete", methods=["POST"])
@role_required("admin")
def delete_patient(patient_id):
    patient = Patient.query.get_or_404(patient_id)
    db.session.delete(patient)
    db.session.commit()
    flash("Patient account deleted.", "info")
    return redirect(url_for("admin.patients"))


# ----------------------------------------------------------------------
# Hospitals
# ----------------------------------------------------------------------
@admin_bp.route("/hospitals")
@role_required("admin")
def hospitals():
    name = request.args.get("name", "").strip()
    city = request.args.get("city", "").strip()
    query = Hospital.query
    if name:
        query = query.filter(Hospital.hospital_name.ilike(f"%{name}%"))
    if city:
        query = query.filter(Hospital.city.ilike(f"%{city}%"))
    page = request.args.get("page", 1, type=int)
    items = query.order_by(Hospital.created_at.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False
    )
    return render_template("admin/hospitals.html", hospitals=items,
                           filters={"name": name, "city": city})


@admin_bp.route("/hospitals/new", methods=["GET", "POST"])
@role_required("admin")
def add_hospital():
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        errors = validate_hospital_form(form)
        if not errors and Hospital.query.filter_by(
            email=form["email"].lower().strip()
        ).first():
            errors.append("A hospital with this email already exists.")
        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            hospital = Hospital(
                hospital_name=form["hospital_name"].strip(),
                email=form["email"].lower().strip(),
                phone=form["phone"].strip(),
                address=form["address"].strip(),
                city=form["city"].strip(),
                is_verified=True,
                is_active=True,
            )
            hospital.set_password(form["password"])
            db.session.add(hospital)
            db.session.commit()
            flash("Hospital added and verified.", "success")
            return redirect(url_for("admin.hospitals"))
    return render_template("admin/hospital_form.html", form=form, editing=False)


@admin_bp.route("/hospitals/<int:hospital_id>", methods=["GET", "POST"])
@role_required("admin")
def hospital_detail(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
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
            flash("Hospital updated.", "success")
            return redirect(url_for("admin.hospital_detail", hospital_id=hospital.id))
    return render_template("admin/hospital_detail.html", hospital=hospital)


@admin_bp.route("/hospitals/<int:hospital_id>/verify", methods=["POST"])
@role_required("admin")
def verify_hospital(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    hospital.is_verified = not hospital.is_verified
    db.session.commit()
    flash(f"Hospital {'verified' if hospital.is_verified else 'unverified'}.", "info")
    return redirect(request.referrer or url_for("admin.hospitals"))


@admin_bp.route("/hospitals/<int:hospital_id>/toggle", methods=["POST"])
@role_required("admin")
def toggle_hospital(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    hospital.is_active = not hospital.is_active
    db.session.commit()
    flash(f"Hospital account {'activated' if hospital.is_active else 'deactivated'}.", "info")
    return redirect(request.referrer or url_for("admin.hospitals"))


@admin_bp.route("/hospitals/<int:hospital_id>/delete", methods=["POST"])
@role_required("admin")
def delete_hospital(hospital_id):
    hospital = Hospital.query.get_or_404(hospital_id)
    if hospital.requests:
        flash("This hospital has blood requests and cannot be deleted. "
              "Deactivate it instead.", "warning")
        return redirect(url_for("admin.hospitals"))
    db.session.delete(hospital)
    db.session.commit()
    flash("Hospital deleted.", "info")
    return redirect(url_for("admin.hospitals"))


# ----------------------------------------------------------------------
# Blood requests
# ----------------------------------------------------------------------
@admin_bp.route("/requests")
@role_required("admin")
def requests_list():
    status = request.args.get("status", "")
    blood_group = request.args.get("blood_group", "")
    urgency = request.args.get("urgency", "")
    city = request.args.get("city", "").strip()

    query = BloodRequest.query
    if status:
        query = query.filter_by(status=status)
    if blood_group in BLOOD_GROUPS:
        query = query.filter_by(blood_group_required=blood_group)
    if urgency:
        query = query.filter_by(urgency=urgency)
    if city:
        query = query.filter(BloodRequest.location.ilike(f"%{city}%"))

    page = request.args.get("page", 1, type=int)
    items = query.order_by(BloodRequest.created_at.desc()).paginate(
        page=page, per_page=PER_PAGE, error_out=False
    )
    return render_template(
        "admin/requests.html", requests=items, blood_groups=BLOOD_GROUPS,
        statuses=[STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
                  STATUS_FULFILLED, STATUS_EXPIRED],
        filters={"status": status, "blood_group": blood_group,
                 "urgency": urgency, "city": city},
    )


@admin_bp.route("/requests/<int:request_id>")
@role_required("admin")
def request_detail(request_id):
    blood_request = BloodRequest.query.get_or_404(request_id)
    matches = find_matching_donors(blood_request, limit=15)
    return render_template("admin/request_detail.html",
                           blood_request=blood_request, matches=matches)


@admin_bp.route("/requests/<int:request_id>/status", methods=["POST"])
@role_required("admin")
def update_request_status(request_id):
    blood_request = BloodRequest.query.get_or_404(request_id)
    new_status = request.form.get("status", "")
    if new_status not in (STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
                          STATUS_FULFILLED, STATUS_EXPIRED):
        flash("Select a valid status.", "danger")
    else:
        blood_request.status = new_status
        db.session.commit()
        flash(f"Request marked as {new_status}.", "success")
    return redirect(url_for("admin.request_detail", request_id=request_id))


@admin_bp.route("/requests/<int:request_id>/delete", methods=["POST"])
@role_required("admin")
def delete_request(request_id):
    blood_request = BloodRequest.query.get_or_404(request_id)
    db.session.delete(blood_request)
    db.session.commit()
    flash("Request deleted.", "info")
    return redirect(url_for("admin.requests_list"))


# ----------------------------------------------------------------------
# Reports and analytics
# ----------------------------------------------------------------------
@admin_bp.route("/analytics")
@role_required("admin")
def analytics():
    donors_by_group = {g: 0 for g in BLOOD_GROUPS}
    for group, count in db.session.query(Donor.blood_group, func.count(Donor.id)).group_by(
        Donor.blood_group
    ):
        donors_by_group[group] = count

    requests_by_group = {g: 0 for g in BLOOD_GROUPS}
    for group, count in db.session.query(
        BloodRequest.blood_group_required, func.count(BloodRequest.id)
    ).group_by(BloodRequest.blood_group_required):
        requests_by_group[group] = count

    requests_by_city = dict(
        Counter(r.location for r in BloodRequest.query.all()).most_common(10)
    )

    status_counts = {
        s: BloodRequest.query.filter_by(status=s).count()
        for s in [STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
                  STATUS_FULFILLED, STATUS_EXPIRED]
    }

    # Completed donations per month, e.g. {"2026-03": 4}
    monthly = Counter()
    for response in DonationResponse.query.filter_by(
        response_status="Donation Completed"
    ).all():
        when = response.donation_date or response.response_date.date()
        monthly[when.strftime("%Y-%m")] += 1
    monthly_donations = dict(sorted(monthly.items()))

    return render_template(
        "admin/analytics.html", donors_by_group=donors_by_group,
        requests_by_group=requests_by_group, requests_by_city=requests_by_city,
        status_counts=status_counts, monthly_donations=monthly_donations,
    )

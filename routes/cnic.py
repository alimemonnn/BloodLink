"""CNIC verification: donor upload, administrator review, and the hospital's nearby-donor view.

* A donor can upload a CNIC at registration or later from ``/donor/cnic``. It is optional: a donor
  without an approved CNIC can still donate, but does not show the "Verified donor" badge.
* Only an administrator can open the stored image, and every view and decision is written to the
  audit log.
* The hospital page ``/hospital/requests/<id>/nearby`` lists donors around the hospital.
"""
import math
from datetime import datetime

from flask import (Blueprint, Response, abort, flash, redirect, render_template,
                   request, url_for)

from models import (CNIC_APPROVED, CNIC_PENDING, CNIC_REJECTED, BloodRequest, Donor,
                    DonorCNIC, db)
from utils import allocation, ratelimit
from utils import cnic as cnic_utils
from utils.auth import current_user, role_required
from utils.nearby import DEFAULT_RADIUS, RADIUS_CHOICES, nearby_donors
from utils.notifications import notify_donor

cnic_bp = Blueprint("cnic", __name__)

PER_PAGE = 15


# ----------------------------------------------------------------------
# Donor: upload or replace
# ----------------------------------------------------------------------
def _settings_url():
    return url_for("security.settings") + "#cnic"


@cnic_bp.route("/donor/cnic", methods=["GET", "POST"])
@role_required("donor")
def donor_cnic():
    """The CNIC form lives on the Account security page; this URL receives the upload."""
    donor = current_user()
    if request.method == "GET":
        return redirect(_settings_url())
    record = donor.cnic
    key = f"cnic-upload:{donor.id}"
    if record is not None and record.is_approved:
        flash("Your CNIC is already verified.", "info")
        return redirect(_settings_url())
    if ratelimit.is_blocked(key, 5, 3600):
        flash("Too many uploads. Please try again in an hour.", "warning")
        return redirect(_settings_url())
    errors, number, data, mime = cnic_utils.validate_submission(
        request.form.to_dict(), request.files, donor=donor, required=True)
    ratelimit.record_failure(key, 3600)
    if errors:
        for error in errors:
            flash(error, "danger")
        return redirect(_settings_url())
    cnic_utils.save_submission(donor, number, data, mime)
    allocation.audit("donor", donor.id, "cnic.submit", "donor", donor.id)
    db.session.commit()
    flash("Your CNIC was sent for review. You will be notified when it is approved.", "success")
    return redirect(_settings_url())


# ----------------------------------------------------------------------
# Administrator: review queue, detail, file, decisions
# ----------------------------------------------------------------------
@cnic_bp.route("/admin/cnic")
@role_required("admin")
def admin_list():
    status = request.args.get("status", CNIC_PENDING)
    query = DonorCNIC.query.join(Donor, Donor.id == DonorCNIC.donor_id)
    if status in (CNIC_PENDING, CNIC_APPROVED, CNIC_REJECTED):
        query = query.filter(DonorCNIC.status == status)
    else:
        status = "all"
    page = request.args.get("page", 1, type=int)
    items = query.order_by(DonorCNIC.submitted_at.desc()).paginate(page=page, per_page=PER_PAGE, error_out=False)
    counts = {s: DonorCNIC.query.filter_by(status=s).count() for s in (CNIC_PENDING, CNIC_APPROVED, CNIC_REJECTED)}
    return render_template("admin/cnic_list.html", items=items, status=status, counts=counts,
                           without_cnic=Donor.query.count() - DonorCNIC.query.count())


@cnic_bp.route("/admin/cnic/<int:donor_id>")
@role_required("admin")
def admin_detail(donor_id):
    donor = Donor.query.get_or_404(donor_id)
    return render_template("admin/cnic_detail.html", donor=donor, record=donor.cnic,
                           responses=sorted(donor.responses, key=lambda r: r.response_date, reverse=True))


@cnic_bp.route("/admin/cnic/<int:donor_id>/file")
@role_required("admin")
def admin_file(donor_id):
    donor = Donor.query.get_or_404(donor_id)
    record = donor.cnic
    if record is None or not record.has_file:
        abort(404)
    data = cnic_utils.unseal(record.file_data)
    if data is None:
        abort(410)                                   # key changed or data damaged
    allocation.audit("admin", current_user().id, "cnic.view", "donor", donor.id)
    db.session.commit()
    response = Response(data, mimetype=record.file_mime)
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Content-Disposition"] = "inline; filename=cnic"
    return response


def _after_decision(donor_id):
    """Back to the review queue when the decision was made from it, otherwise to the donor's page."""
    nxt = request.form.get("next", "")
    if nxt.startswith("/admin/cnic") and not nxt.startswith("//"):
        return nxt
    return url_for("cnic.admin_detail", donor_id=donor_id)


@cnic_bp.route("/admin/cnic/<int:donor_id>/approve", methods=["POST"])
@role_required("admin")
def admin_approve(donor_id):
    donor = Donor.query.get_or_404(donor_id)
    record = donor.cnic
    if record is None:
        abort(404)
    if not record.has_file:
        flash("This donor has not uploaded the CNIC image yet.", "warning")
        return redirect(url_for("cnic.admin_detail", donor_id=donor.id))
    if record.status == CNIC_APPROVED:
        flash("This CNIC is already approved.", "info")
        return redirect(url_for("cnic.admin_detail", donor_id=donor.id))
    admin = current_user()
    record.status = CNIC_APPROVED
    record.reject_reason = None
    record.reviewed_at = datetime.utcnow()
    record.reviewed_by_admin_id = admin.id
    allocation.audit("admin", admin.id, "cnic.approve", "donor", donor.id)
    notify_donor(donor.id, "Your CNIC was approved. You now show the Verified donor badge.", commit=False)
    db.session.commit()
    flash(f"{donor.name} is now a Verified donor.", "success")
    return redirect(_after_decision(donor.id))


@cnic_bp.route("/admin/cnic/<int:donor_id>/reject", methods=["POST"])
@role_required("admin")
def admin_reject(donor_id):
    donor = Donor.query.get_or_404(donor_id)
    record = donor.cnic
    if record is None:
        abort(404)
    if not record.has_file:
        flash("This donor has not uploaded the CNIC image yet.", "warning")
        return redirect(url_for("cnic.admin_detail", donor_id=donor.id))
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Please give a short reason so the donor can fix it.", "danger")
        return redirect(url_for("cnic.admin_detail", donor_id=donor.id))
    admin = current_user()
    record.status = CNIC_REJECTED
    record.reject_reason = reason[:255]
    record.reviewed_at = datetime.utcnow()
    record.reviewed_by_admin_id = admin.id
    allocation.audit("admin", admin.id, "cnic.reject", "donor", donor.id, reason)
    notify_donor(donor.id, "Your CNIC could not be verified. Open CNIC verification to see why and upload it again.",
                 commit=False)
    db.session.commit()
    flash("The CNIC was rejected and the donor was told why.", "success")
    return redirect(_after_decision(donor.id))


# ----------------------------------------------------------------------
# Hospital: donors around the hospital (shown right after approving a request)
# ----------------------------------------------------------------------
def _gps_point(args):
    """A valid (lat, lng) from the query string, or None."""
    try:
        lat, lng = float(args.get("lat", "")), float(args.get("lng", ""))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return round(lat, 5), round(lng, 5)


@cnic_bp.route("/hospital/requests/<int:request_id>/nearby")
@role_required("hospital")
def hospital_nearby(request_id):
    hospital = current_user()
    blood_request = BloodRequest.query.get_or_404(request_id)
    if blood_request.hospital_id != hospital.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))
    radius = request.args.get("radius", DEFAULT_RADIUS, type=int)
    if radius not in RADIUS_CHOICES:
        radius = None if request.args.get("radius") == "0" else DEFAULT_RADIUS
    verified_only = request.args.get("verified") == "1"
    gps = _gps_point(request.args)
    if gps is not None:
        source = "gps"
    elif hospital.lat is not None and hospital.lng is not None:
        source = "saved"
    else:
        source = "city"
    rows, scale, has_position = nearby_donors(blood_request, radius, verified_only, origin=gps)
    return render_template("hospital/nearby.html", hospital=hospital, blood_request=blood_request,
                           rows=rows, scale=scale, has_position=has_position, radius=radius,
                           radius_choices=RADIUS_CHOICES, verified_only=verified_only,
                           source=source, gps=gps)


@cnic_bp.route("/hospital/requests/<int:request_id>/position", methods=["POST"])
@role_required("hospital")
def hospital_save_position(request_id):
    """Save the hospital's GPS reading so every later search starts from the real building."""
    hospital = current_user()
    blood_request = BloodRequest.query.get_or_404(request_id)
    if blood_request.hospital_id != hospital.id:
        flash("Unauthorized access.", "danger")
        return redirect(url_for("hospital.requests_list"))
    point = _gps_point(request.form)
    if point is None:
        flash("That location was not valid. Please allow location access and try again.", "danger")
    else:
        hospital.lat, hospital.lng = point
        allocation.audit("hospital", hospital.id, "hospital.position", "hospital", hospital.id)
        db.session.commit()
        flash("Hospital location saved. Distances now start from it.", "success")
    return redirect(url_for("cnic.hospital_nearby", request_id=request_id))

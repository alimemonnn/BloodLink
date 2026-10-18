"""QR check-in at the hospital, no-show records, and donation certificates."""
from datetime import datetime

from flask import (Blueprint, Response, abort, current_app, flash, redirect, render_template,
                   request, url_for)

from models import RESP_COMPLETED, DonationResponse, db
from utils import allocation, chat, ratelimit, trust
from utils.auth import current_user, role_required

trust_bp = Blueprint("trust", __name__)


def _own_response_or_404(response_id, hospital):
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.request.hospital_id != hospital.id:
        abort(404)
    return resp


# --------------------------------------------------------------- donor shows QR
@trust_bp.route("/donor/checkin/<int:response_id>")
@role_required("donor")
def donor_checkin(response_id):
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.donor_id != current_user().id:
        abort(404)
    if not trust.can_check_in(resp):
        flash("A check-in code is available once the hospital has set an appointment.", "info")
        return redirect(url_for("donor.history"))
    return render_template("trust/donor_checkin.html", resp=resp, code=trust.checkin_code(resp),
                           qr=trust.qr_data_uri(trust.checkin_url(resp)))


# ----------------------------------------------------------- hospital scans it
@trust_bp.route("/hospital/checkin", methods=["GET", "POST"])
@role_required("hospital")
def checkin_scan():
    hospital = current_user()
    code = (request.values.get("code") or "").strip()
    # A scanned QR holds a full URL ending in the code; accept either.
    code = code.rsplit("code=", 1)[-1].split("&")[0] if "code=" in code else code
    resp = None
    if code:
        key = f"checkin|{request.remote_addr}"
        if ratelimit.is_blocked(key, 30, 600):
            flash("Too many attempts. Please wait a few minutes.", "danger")
            return render_template("trust/checkin.html", resp=None, code=code), 429
        resp = trust.resolve_checkin(code)
        if resp is None or resp.request.hospital_id != hospital.id:
            ratelimit.record_failure(key, 600)
            flash("That code is not valid for this hospital.", "danger")
            resp = None
    return render_template("trust/checkin.html", resp=resp, code=code,
                           already=bool(resp and resp.checked_in_at), can_check_in=bool(resp and trust.can_check_in(resp)))


@trust_bp.route("/hospital/checkin/<int:response_id>/arrived", methods=["POST"])
@role_required("hospital")
def mark_arrived(response_id):
    hospital = current_user()
    resp = _own_response_or_404(response_id, hospital)
    if not trust.can_check_in(resp):
        flash("This offer is not active, so it cannot be checked in.", "warning")
    elif resp.checked_in_at:
        flash("This donor was already checked in.", "info")
    else:
        resp.checked_in_at = datetime.utcnow()
        chat.add_event(resp, "The donor arrived and was checked in by the hospital.")
        allocation.audit("hospital", hospital.id, "donor.checked_in", "response", resp.id)
        db.session.commit()
        flash(f"{resp.donor.name} is checked in. Confirm the donation once blood has been collected.", "success")
    return redirect(url_for("hospital.request_detail", request_id=resp.request_id))


@trust_bp.route("/hospital/responses/<int:response_id>/no-show", methods=["POST"])
@role_required("hospital")
def no_show(response_id):
    hospital = current_user()
    resp = _own_response_or_404(response_id, hospital)
    if resp.checked_in_at:
        flash("This donor already arrived, so it cannot be recorded as a no-show.", "warning")
        return redirect(url_for("hospital.request_detail", request_id=resp.request_id))
    try:
        allocation.cancel_response(resp.id, "hospital", hospital.id, "Did not attend")
    except allocation.AllocationError as err:
        flash(str(err), "warning")
        return redirect(url_for("hospital.request_detail", request_id=resp.request_id))
    resp = db.session.get(DonationResponse, response_id)
    resp.no_show_at = datetime.utcnow()
    chat.add_event(resp, "The hospital recorded that the donor did not attend.")
    allocation.audit("hospital", hospital.id, "donor.no_show", "response", resp.id)
    db.session.commit()
    flash("Recorded as a no-show. The request stays open for other donors.", "info")
    return redirect(url_for("hospital.request_detail", request_id=resp.request_id))


# ---------------------------------------------------------------- certificates
@trust_bp.route("/donor/certificate/<int:response_id>.pdf")
@role_required("donor")
def certificate(response_id):
    resp = db.session.get(DonationResponse, response_id)
    if resp is None or resp.donor_id != current_user().id or resp.response_status != RESP_COMPLETED:
        abort(404)
    return Response(trust.certificate_pdf(resp), mimetype="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="bloodlink-certificate-{resp.id}.pdf"'})


@trust_bp.route("/verify", methods=["GET", "POST"])
@trust_bp.route("/verify/<code>")
def verify(code=None):
    code = (code or request.values.get("code") or "").strip()
    if not code:
        return render_template("trust/verify.html", code="", resp=None, checked=False)
    key = f"verify|{request.remote_addr}"
    if ratelimit.is_blocked(key, 30, 60):
        return render_template("trust/verify.html", code=code, resp=None, checked=True), 429
    ratelimit.record_failure(key, 60)
    resp = trust.resolve_certificate(code)
    return render_template("trust/verify.html", code=code, resp=resp, checked=True,
                           who=trust.public_name(resp.donor) if resp else None)

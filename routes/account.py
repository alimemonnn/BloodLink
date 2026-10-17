"""Account-wide privacy tools: data export, preferences and self-service deletion."""
import json

from flask import (Blueprint, Response, flash, redirect, render_template,
                   request, session, url_for)

from models import LIVE_STATUSES, db
from utils import privacy, ratelimit
from utils.auth import current_user, dashboard_endpoint, login_required, logout_user
from utils.validators import checked

account_bp = Blueprint("account", __name__, url_prefix="/account")


@account_bp.route("/export")
@login_required
def export():
    user = current_user()
    if user is None or session.get("role") == "admin":
        flash("Administrator accounts are managed by the system owner.", "info")
        return redirect(url_for(dashboard_endpoint()))
    data = privacy.export_data(user.role, user)
    return Response(json.dumps(data, indent=2, default=str), mimetype="application/json",
                    headers={"Content-Disposition": f"attachment; filename=bloodlink-{user.role}-data.json"})


@account_bp.route("/preferences", methods=["POST"])
@login_required
def preferences():
    """Donor consents can be withdrawn as easily as they were given."""
    user = current_user()
    if user is None or user.role != "donor":
        return redirect(url_for(dashboard_endpoint()))
    share = checked(request.form, "share_contact_consent")
    email = checked(request.form, "email_opt_in")
    if share != user.share_contact_consent:
        user.share_contact_consent = share
        privacy.set_consent("donor", user.id, "contact_sharing", share)
    if email != user.email_opt_in:
        user.email_opt_in = email
        privacy.set_consent("donor", user.id, "email_notifications", email)
    db.session.commit()
    flash("Your privacy choices were saved.", "success")
    return redirect(url_for("donor.profile"))


@account_bp.route("/delete", methods=["GET", "POST"])
@login_required
def delete():
    user = current_user()
    role = session.get("role")
    if user is None or role == "admin":
        flash("Administrator accounts cannot be deleted here.", "info")
        return redirect(url_for(dashboard_endpoint()))
    if role == "hospital":
        flash("Hospital accounts are closed by an administrator. Please send a request.", "info")
        return redirect(url_for("legal.data_request", kind="delete"))

    live = 0
    if role == "patient":
        live = sum(1 for r in user.requests if r.status in LIVE_STATUSES)

    if request.method == "POST":
        key = f"delete|{role}|{user.id}"
        if ratelimit.is_blocked(key, 5, 600):
            flash("Too many attempts. Please wait a few minutes.", "danger")
        elif not user.check_password(request.form.get("password", "")):
            ratelimit.record_failure(key, 600)
            flash("Your password is incorrect.", "danger")
        elif request.form.get("confirm_text", "").strip() != "DELETE":
            flash("Type DELETE in capital letters to confirm.", "danger")
        else:
            result = privacy.erase_donor(user) if role == "donor" else privacy.erase_patient(user)
            logout_user()
            flash("Your account and personal data were erased. "
                  + ("A verified donation count is kept without your identity."
                     if result == "anonymised" else ""), "info")
            return redirect(url_for("public.index"))
    return render_template("account/delete.html", role=role, live_requests=live)

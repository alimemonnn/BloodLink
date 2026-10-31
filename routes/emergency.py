"""Emergency requests that a hospital posts itself."""
from flask import Blueprint, flash, redirect, render_template, request, url_for

from utils import emergency
from utils.auth import current_user, role_required

emergency_bp = Blueprint("emergency", __name__)


@emergency_bp.route("/hospital/emergency", methods=["GET", "POST"])
@role_required("hospital")
def new_emergency():
    hospital = current_user()
    if request.method == "POST":
        try:
            req, notified = emergency.create(hospital, request.form)
        except emergency.EmergencyError as err:
            flash(str(err), "danger")
            return render_template("hospital/emergency.html", groups=emergency.BLOOD, hours=emergency.HOURS, form=request.form), 400
        flash(f"Emergency request #{req.id} is live. {notified} matching donor(s) were alerted now.", "success")
        return redirect(url_for("hospital.request_detail", request_id=req.id))
    return render_template("hospital/emergency.html", groups=emergency.BLOOD, hours=emergency.HOURS, form={})

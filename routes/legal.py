"""Policies, licences, data-rights requests and email unsubscribe."""
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)

from models import ContactMessage, DataRequest, Donor, db
from utils import mailer, privacy, ratelimit
from utils.validators import (DATA_REQUEST_KINDS, checked,
                              validate_data_request_form)

legal_bp = Blueprint("legal", __name__)


@legal_bp.route("/privacy")
def privacy_policy():
    return render_template("legal/privacy.html")


@legal_bp.route("/terms")
def terms():
    return render_template("legal/terms.html")


@legal_bp.route("/refund-policy")
def refund_policy():
    return render_template("legal/refund.html")


@legal_bp.route("/cookies")
def cookies():
    return render_template("legal/cookies.html")


@legal_bp.route("/licenses")
def licenses():
    return render_template("legal/licenses.html")


@legal_bp.route("/accessibility")
def accessibility():
    return render_template("legal/accessibility.html")


@legal_bp.route("/data-request", methods=["GET", "POST"])
def data_request():
    """Anyone (with or without an account) can ask for access, correction or deletion."""
    form = {"kind": request.args.get("kind", "delete")}
    if request.method == "POST":
        form = request.form.to_dict()
        key = f"datareq|{request.remote_addr}"
        if ratelimit.is_blocked(key, 5, 3600):
            flash("Too many requests from this address. Please try again later.", "danger")
            return render_template("legal/data_request.html", form=form, kinds=DATA_REQUEST_KINDS), 429
        errors = validate_data_request_form(form)
        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            ratelimit.record_failure(key, 3600)
            db.session.add(DataRequest(kind=form["kind"], name=form.get("name", "").strip(),
                                       email=form["email"].strip().lower(),
                                       details=form.get("details", "").strip()))
            db.session.commit()
            flash("Your request was received. An administrator will verify your identity "
                  "by email before changing or deleting anything.", "success")
            return redirect(url_for("legal.data_request"))
    return render_template("legal/data_request.html", form=form, kinds=DATA_REQUEST_KINDS)


@legal_bp.route("/unsubscribe/<token>", methods=["GET", "POST"])
def unsubscribe(token):
    """One-click unsubscribe. The signed token is the authorisation (no login needed)."""
    donor_id = mailer.read_unsubscribe_token(token)
    donor = db.session.get(Donor, donor_id) if donor_id else None
    if donor is None:
        return render_template("legal/unsubscribe.html", state="invalid"), 400
    if request.method == "POST":
        if donor.email_opt_in:
            donor.email_opt_in = False
            privacy.set_consent("donor", donor.id, "email_notifications", False)
            db.session.commit()
        return render_template("legal/unsubscribe.html", state="done")
    return render_template("legal/unsubscribe.html", state="confirm", token=token)

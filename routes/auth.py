"""Registration, login and logout for all four roles."""
from datetime import datetime

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)

from models import Admin, Donor, Hospital, Patient, db
from utils import ratelimit
from utils.auth import (dashboard_endpoint, login_user, logout_user,
                        remember_next, take_next)
from utils.matching import BLOOD_GROUPS
from utils.validators import (parse_date, validate_donor_form,
                              validate_hospital_form, validate_patient_form)

auth_bp = Blueprint("auth", __name__)

ROLE_MODELS = {"admin": Admin, "donor": Donor, "patient": Patient, "hospital": Hospital}


def _email_taken(email):
    """An email address must be unique across every account type."""
    email = email.lower().strip()
    for model in ROLE_MODELS.values():
        if model.query.filter_by(email=email).first():
            return True
    return False


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.args.get("next"):
        remember_next(request.args["next"])
    if session.get("user_id"):
        return redirect(take_next() or url_for(dashboard_endpoint()))

    if request.method == "POST":
        role = request.form.get("role", "")
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        model = ROLE_MODELS.get(role)

        # Brute-force protection: too many failures from one address for one
        # email locks further attempts for a few minutes.
        limit_key = f"{request.remote_addr}|{email}"
        max_tries = current_app.config["LOGIN_MAX_ATTEMPTS"]
        window = current_app.config["LOGIN_WINDOW_SECONDS"]
        if ratelimit.is_blocked(limit_key, max_tries, window):
            flash("Too many failed attempts. Please wait a few minutes and try again.", "danger")
            return render_template("auth/login.html", email=email, role=role), 429

        if model is None:
            flash("Please choose the account type you are logging in with.", "danger")
            return render_template("auth/login.html", email=email, role=role)

        user = model.query.filter_by(email=email).first()
        # The same message is used for a wrong email and a wrong password so
        # the form cannot be used to discover which emails are registered.
        if user is None or not user.check_password(password):
            ratelimit.record_failure(limit_key, window)
            flash("Incorrect email or password.", "danger")
            return render_template("auth/login.html", email=email, role=role)

        if getattr(user, "is_active", True) is False:
            flash("This account has been deactivated. Please contact the administrator.", "danger")
            return render_template("auth/login.html", email=email, role=role)

        if role == "hospital" and not user.is_verified:
            flash("This hospital account is waiting for admin approval.", "warning")
            return render_template("auth/login.html", email=email, role=role)

        ratelimit.reset(limit_key)
        destination = take_next()          # must be read before login_user()
        # Record when this account was last active, for the admin "Users" view.
        user.last_login_at = datetime.utcnow()
        db.session.commit()
        login_user(user)
        flash(f"Welcome back, {user.name}.", "success")
        return redirect(destination or url_for(dashboard_endpoint(role)))

    return render_template("auth/login.html", email="", role=request.args.get("role", ""))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("public.index"))


@auth_bp.route("/register")
def register():
    return render_template("auth/register.html")


# ----------------------------------------------------------------------
# Donor registration
# ----------------------------------------------------------------------
@auth_bp.route("/register/donor", methods=["GET", "POST"])
def register_donor():
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        errors = validate_donor_form(form)
        if not errors and _email_taken(form.get("email", "")):
            errors.append("An account with this email already exists.")

        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            donor = Donor(
                name=form["name"].strip(),
                email=form["email"].lower().strip(),
                phone=form["phone"].strip(),
                blood_group=form["blood_group"],
                city=form["city"].strip(),
                area=form.get("area", "").strip(),
                last_donation_date=parse_date(form.get("last_donation_date")),
                availability=form.get("availability", "Available"),
            )
            donor.set_password(form["password"])
            donor.refresh_eligibility()
            db.session.add(donor)
            db.session.commit()
            destination = take_next()
            login_user(donor)
            flash("Your donor account is ready. Thank you for joining BloodLink.", "success")
            return redirect(destination or url_for("donor.dashboard"))

    return render_template("auth/register_donor.html", form=form, blood_groups=BLOOD_GROUPS)


# ----------------------------------------------------------------------
# Patient registration
# ----------------------------------------------------------------------
@auth_bp.route("/register/patient", methods=["GET", "POST"])
def register_patient():
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        errors = validate_patient_form(form)
        if not errors and _email_taken(form.get("email", "")):
            errors.append("An account with this email already exists.")

        if errors:
            for error in errors:
                flash(error, "danger")
        else:
            patient = Patient(
                name=form["name"].strip(),
                email=form["email"].lower().strip(),
                phone=form["phone"].strip(),
                city=form["city"].strip(),
                address=form.get("address", "").strip(),
            )
            patient.set_password(form["password"])
            db.session.add(patient)
            db.session.commit()
            destination = take_next()
            login_user(patient)
            flash("Your account is ready. You can post a blood request now.", "success")
            return redirect(destination or url_for("patient.dashboard"))

    return render_template("auth/register_patient.html", form=form)


# ----------------------------------------------------------------------
# Hospital registration (needs admin approval before first login)
# ----------------------------------------------------------------------
@auth_bp.route("/register/hospital", methods=["GET", "POST"])
def register_hospital():
    form = {}
    if request.method == "POST":
        form = request.form.to_dict()
        errors = validate_hospital_form(form)
        if not errors and _email_taken(form.get("email", "")):
            errors.append("An account with this email already exists.")

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
                is_verified=False,   # admin must approve first
            )
            hospital.set_password(form["password"])
            db.session.add(hospital)
            db.session.commit()
            flash(
                "Hospital registered. An administrator will verify the account "
                "before you can log in.",
                "info",
            )
            return redirect(url_for("auth.login", role="hospital"))

    return render_template("auth/register_hospital.html", form=form)

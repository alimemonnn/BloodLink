"""Forgot password, email verification and two-factor login."""
from datetime import datetime

import segno
from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)

from models import db
from utils import allocation, ratelimit, security
from utils.auth import current_user, dashboard_endpoint, login_required, login_user, take_next
from utils.validators import validate_password
from utils import mailer

security_bp = Blueprint("security", __name__)
GENERIC = "If that email belongs to an account, we have sent a link. It works for one hour."


def _qr(uri):
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


# ------------------------------------------------------------ forgot password
@security_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").lower().strip()
        key = f"reset|{request.remote_addr}|{email}"
        if ratelimit.is_blocked(key, 5, 3600):
            flash("Too many requests. Please try again in an hour.", "danger")
            return render_template("security/forgot.html"), 429
        ratelimit.record_failure(key, 3600)
        role, user = security.find_account(email)
        if user is not None and getattr(user, "is_active", True):
            link = url_for("security.reset_password", token=security.reset_token(role, user), _external=True)
            mailer.deliver(user.email, "Reset your BloodLink password",
                           f"Hello {user.name},\n\nUse this link to choose a new password. It works for "
                           f"one hour and only once:\n{link}\n\nIf you did not ask for this, ignore this email; "
                           "your password has not changed.")
            allocation.audit(role, user.id, "password.reset_requested", "account", user.id)
            db.session.commit()
        flash(GENERIC, "info")                      # same answer whether or not the email exists
        return redirect(url_for("auth.login"))
    return render_template("security/forgot.html")


@security_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    role, user = security.read_reset_token(token)
    if user is None:
        flash("That reset link is invalid or has expired. Please ask for a new one.", "danger")
        return redirect(url_for("security.forgot_password"))
    if request.method == "POST":
        errors = validate_password(request.form.get("password", ""), request.form.get("confirm_password"))
        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("security/reset.html", token=token)
        user.set_password(request.form["password"])
        allocation.audit(role, user.id, "password.reset", "account", user.id)
        db.session.commit()
        flash("Your password was changed. Please log in.", "success")
        return redirect(url_for("auth.login", role=role))
    return render_template("security/reset.html", token=token)


# ----------------------------------------------------------- email verification
@security_bp.route("/account/security")
@login_required
def settings():
    user = current_user()
    return render_template("security/settings.html", user=user, role=session["role"],
                           codes_left=security.recovery_codes_left(user),
                           required=session["role"] in current_app.config["REQUIRE_2FA_ROLES"])


@security_bp.route("/account/verify-email/send", methods=["POST"])
@login_required
def send_verification():
    user, role = current_user(), session["role"]
    if user.email_verified_at:
        flash("Your email is already verified.", "info")
    else:
        link = url_for("security.verify_email", token=security.verify_token(role, user), _external=True)
        mailer.deliver(user.email, "Confirm your BloodLink email",
                       f"Hello {user.name},\n\nConfirm that this is your email address:\n{link}\n")
        flash("We sent a confirmation link to your email.", "success")
    return redirect(url_for("security.settings"))


@security_bp.route("/verify-email/<token>")
def verify_email(token):
    role, user = security.read_verify_token(token)
    if user is None:
        flash("That confirmation link is invalid or has expired.", "danger")
        return redirect(url_for("public.index"))
    user.email_verified_at = user.email_verified_at or datetime.utcnow()
    db.session.commit()
    flash("Thank you, your email is confirmed.", "success")
    return redirect(url_for("security.settings") if session.get("user_id") else url_for("auth.login"))


# --------------------------------------------------------------- 2FA set-up
@security_bp.route("/account/2fa/start", methods=["POST"])
@login_required
def start_2fa():
    user = current_user()
    if user.has_2fa:
        flash("Two-factor login is already on.", "info")
        return redirect(url_for("security.settings"))
    secret = security.new_secret()
    session["pending_totp_secret"] = secret
    return render_template("security/enable_2fa.html", secret=secret,
                           qr=_qr(security.provisioning_uri(user, secret)))


@security_bp.route("/account/2fa/enable", methods=["POST"])
@login_required
def enable_2fa():
    user, role = current_user(), session["role"]
    secret = session.get("pending_totp_secret")
    step = security.check_totp(secret, request.form.get("code", "")) if secret else None
    if step is None:
        flash("That code did not match. Check your phone's clock and try again.", "danger")
        if secret:
            return render_template("security/enable_2fa.html", secret=secret,
                                   qr=_qr(security.provisioning_uri(user, secret)))
        return redirect(url_for("security.settings"))
    codes = security.new_recovery_codes()
    user.totp_secret, user.totp_enabled_at, user.totp_last_step = security.seal(secret), datetime.utcnow(), step
    security.store_recovery_codes(user, codes)
    allocation.audit(role, user.id, "2fa.enabled", "account", user.id)
    db.session.commit()
    session.pop("pending_totp_secret", None)
    return render_template("security/recovery_codes.html", codes=codes)


@security_bp.route("/account/2fa/disable", methods=["POST"])
@login_required
def disable_2fa():
    user, role = current_user(), session["role"]
    if role in current_app.config["REQUIRE_2FA_ROLES"]:
        flash("Two-factor login is required for this account type and cannot be turned off.", "warning")
        return redirect(url_for("security.settings"))
    ok = user.check_password(request.form.get("password", "")) and _second_factor_ok(user, request.form.get("code", ""))
    if not ok:
        flash("Your password or code was not correct.", "danger")
        return redirect(url_for("security.settings"))
    user.totp_secret = user.totp_enabled_at = user.totp_last_step = user.recovery_codes = None
    allocation.audit(role, user.id, "2fa.disabled", "account", user.id)
    db.session.commit()
    flash("Two-factor login is now off.", "success")
    return redirect(url_for("security.settings"))


@security_bp.route("/account/2fa/new-codes", methods=["POST"])
@login_required
def new_codes():
    user = current_user()
    if not (user.has_2fa and user.check_password(request.form.get("password", ""))):
        flash("Your password was not correct.", "danger")
        return redirect(url_for("security.settings"))
    codes = security.new_recovery_codes()
    security.store_recovery_codes(user, codes)
    db.session.commit()
    return render_template("security/recovery_codes.html", codes=codes)


def _second_factor_ok(user, code):
    """Accept a current authenticator code or an unused recovery code."""
    secret = security.user_secret(user)
    step = security.check_totp(secret, code, user.totp_last_step) if secret else None
    if step is not None:
        user.totp_last_step = step
        return True
    return security.use_recovery_code(user, code)


# ---------------------------------------------------------------- 2FA at login
@security_bp.route("/login/2fa", methods=["GET", "POST"])
def login_2fa():
    pending = session.get("pending_2fa")
    if not pending:
        return redirect(url_for("auth.login"))
    user = security.load_account(pending["role"], pending["id"])
    if user is None or not user.has_2fa:
        session.pop("pending_2fa", None)
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        key = f"2fa|{request.remote_addr}|{pending['role']}|{pending['id']}"
        if ratelimit.is_blocked(key, current_app.config["LOGIN_MAX_ATTEMPTS"], current_app.config["LOGIN_WINDOW_SECONDS"]):
            flash("Too many wrong codes. Please wait a few minutes.", "danger")
            return render_template("security/challenge.html"), 429
        if _second_factor_ok(user, request.form.get("code", "")):
            ratelimit.reset(key)
            session.pop("pending_2fa", None)
            user.last_login_at = datetime.utcnow()
            db.session.commit()
            destination = pending.get("next")
            login_user(user)
            flash(f"Welcome back, {user.name}.", "success")
            return redirect(destination or url_for(dashboard_endpoint(pending["role"])))
        db.session.rollback()
        ratelimit.record_failure(key, current_app.config["LOGIN_WINDOW_SECONDS"])
        flash("That code was not correct.", "danger")
    return render_template("security/challenge.html")

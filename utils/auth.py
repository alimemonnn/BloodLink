"""Session authentication helpers and role-based access control."""
from functools import wraps

from flask import abort, flash, redirect, session, url_for

from models import Admin, Donor, Hospital, Patient

ROLE_MODELS = {
    "admin": Admin,
    "donor": Donor,
    "patient": Patient,
    "hospital": Hospital,
}

DASHBOARD_ENDPOINTS = {
    "admin": "admin.dashboard",
    "donor": "donor.dashboard",
    "patient": "patient.dashboard",
    "hospital": "hospital.dashboard",
}


def login_user(user):
    session.clear()
    session["user_id"] = user.id
    session["role"] = user.role
    session["user_name"] = user.name
    session.permanent = True


def logout_user():
    session.clear()


def current_user():
    """Load the logged-in user object, or None."""
    role = session.get("role")
    user_id = session.get("user_id")
    model = ROLE_MODELS.get(role)
    if not model or not user_id:
        return None
    return model.query.get(user_id)


def safe_next(url):
    """Accept only in-site relative paths, so a login link can never be
    used to bounce somebody to another website (open-redirect protection)."""
    if url and url.startswith("/") and not url.startswith("//") and "\\" not in url:
        return url
    return None


def remember_next(url):
    """Remember where to send the visitor after they log in or register."""
    url = safe_next(url)
    if url:
        session["next_url"] = url


def take_next():
    """Read the remembered destination. Call BEFORE login_user(), which
    clears the session."""
    return safe_next(session.get("next_url"))


def dashboard_endpoint(role=None):
    return DASHBOARD_ENDPOINTS.get(role or session.get("role"), "public.index")


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapper


def role_required(*roles):
    """Block users whose session role is not in `roles`.

    This is what stops a donor from opening the admin dashboard by simply
    typing the URL.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get("user_id"):
                flash("Please log in to continue.", "warning")
                return redirect(url_for("auth.login"))
            if session.get("role") not in roles:
                abort(403)
            user = current_user()
            if user is None:
                session.clear()
                flash("Your session has ended. Please log in again.", "warning")
                return redirect(url_for("auth.login"))
            if getattr(user, "is_active", True) is False:
                session.clear()
                flash("This account has been deactivated. Contact the administrator.", "danger")
                return redirect(url_for("auth.login"))
            return view(*args, **kwargs)

        return wrapper

    return decorator

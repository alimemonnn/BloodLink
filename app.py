"""BloodLink - Blood Donor & Emergency Request Network.

Entry point. Run with:  python app.py
"""
import hmac
import os
import secrets
from datetime import datetime

from flask import Flask, abort, render_template, request, session
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from config import IS_PRODUCTION, Config
from models import Admin, db
from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.donor import donor_bp
from routes.hospital import hospital_bp
from routes.patient import patient_bp
from routes.public import public_bp
from utils.auth import current_user, dashboard_endpoint
from utils.maintenance import expire_old_requests
from utils.notifications import unread_count


def create_app(config_class=Config):
    """Application factory: builds and configures the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)

    if IS_PRODUCTION:
        # Behind Render's proxy: trust X-Forwarded-* so we see the real client
        # IP (needed for rate limiting) and know the request was HTTPS.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)

    # Blueprints keep each role's routes in its own module.
    app.register_blueprint(public_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(donor_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(hospital_bp)
    app.register_blueprint(admin_bp)

    # ------------------------------------------------------------------
    # Template helpers available on every page
    # ------------------------------------------------------------------
    @app.context_processor
    def inject_globals():
        user = current_user()
        return {
            "csrf_token": csrf_token,
            "current_user": user,
            "current_role": session.get("role"),
            "dashboard_url": dashboard_endpoint(),
            "unread_notifications": unread_count(user.id) if user and user.role == "donor" else 0,
            "now": datetime.utcnow(),
        }

    @app.template_filter("wa_number")
    def wa_number(phone):
        """03001234567 -> 923001234567 (the format wa.me links expect)."""
        digits = "".join(c for c in (phone or "") if c.isdigit())
        if digits.startswith("00"):
            digits = digits[2:]
        elif digits.startswith("0"):
            digits = "92" + digits[1:]
        return digits

    # ------------------------------------------------------------------
    # CSRF protection: every state-changing request must carry the token
    # that was placed in the user's session. A foreign website cannot read
    # it, so it cannot forge "approve", "cancel" or "fulfil" clicks.
    # ------------------------------------------------------------------
    @app.before_request
    def csrf_protect():
        if not app.config.get("WTF_CSRF_ENABLED", True):
            return
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
            expected = session.get("_csrf", "")
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.before_request
    def housekeeping():
        # Approved requests older than their expiry date are closed
        # automatically so donors never see stale requests.
        expire_old_requests()

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------
    @app.errorhandler(400)
    def bad_request(error):
        return render_template("errors/400.html"), 400

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(error):
        db.session.rollback()
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()
        _migrate_schema()
        _bootstrap_admin(app)
        # Close the connection used above so gunicorn workers never share it.
        db.engine.dispose()

    return app


def csrf_token():
    """Return this session's CSRF token, creating it on first use."""
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def _migrate_schema():
    """Add newly introduced, nullable columns to already-existing tables.

    ``db.create_all()`` only creates tables that do not exist yet -- it will
    never add a column to a table that is already there. Without this, a
    database created before a field such as ``last_login_at`` existed would
    start raising "no such column" errors the moment the app tried to use
    it. This function only ever ADDS a nullable column; it never drops or
    rewrites a table, so existing rows (and their data) are left alone.
    """
    engine = db.engine
    inspector = inspect(engine)
    datetime_type = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP"

    # table name -> [(column name, SQL type), ...]
    additions = {
        "donors": [("last_login_at", datetime_type)],
        "patients": [("last_login_at", datetime_type)],
        "hospitals": [("last_login_at", datetime_type)],
        "admins": [("last_login_at", datetime_type)],
    }

    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in additions.items():
            if table not in existing_tables:
                continue  # brand-new database: create_all() already added it with every column
            existing_columns = {c["name"] for c in inspector.get_columns(table)}
            for name, col_type in columns:
                if name not in existing_columns:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}"))


def _bootstrap_admin(app):
    """Create the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD.

    This is how you get an admin on the live database without publishing a
    default password in the README. It does nothing if an admin exists.
    """
    email = app.config.get("ADMIN_EMAIL")
    password = app.config.get("ADMIN_PASSWORD")
    if not email or not password or Admin.query.first():
        return
    admin = Admin(name="Administrator", email=email)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)

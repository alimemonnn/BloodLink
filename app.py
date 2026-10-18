"""BloodLink - Blood Donor & Emergency Request Network.

Entry point. Run with:  python app.py
"""
import hmac
import logging
import os
import secrets
import shutil
from datetime import datetime

import click
from flask_migrate import Migrate
from flask import (Flask, abort, flash, g, jsonify, redirect, render_template, request,
                   session, url_for)
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from config import IS_PRODUCTION, Config
from models import Admin, ChatReport, db
from routes.account import account_bp
from routes.admin import admin_bp
from routes.auth import auth_bp
from routes.chat import chat_bp
from routes.security import security_bp
from routes.engage import engage_bp
from routes.trust import trust_bp
from routes.community import community_bp
from routes.api import api_bp
from routes.donor import donor_bp
from routes.hospital import hospital_bp
from routes.legal import legal_bp
from routes.patient import patient_bp
from routes.public import public_bp
from utils.auth import current_user, dashboard_endpoint
from utils import i18n, observability, ratelimit
from utils.maintenance import expire_old_requests
from utils.chat import unread_total
from utils.notifications import unread_count

CSRF_EXEMPT_ENDPOINTS = {"legal.unsubscribe"}     # authorised by a signed token instead


def create_app(config_class=Config):
    """Application factory: builds and configures the Flask app."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    app.config["IS_PRODUCTION"] = IS_PRODUCTION
    observability.init_logging(app, IS_PRODUCTION)
    observability.init_sentry(app)
    if app.config["REDIS_URL"]:
        ratelimit.init_redis(app.config["REDIS_URL"])

    if IS_PRODUCTION:
        # Behind Render's proxy: trust X-Forwarded-* so we see the real client
        # IP (needed for rate limiting) and know the request was HTTPS.
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    Migrate(app, db, compare_type=True)

    app.register_blueprint(api_bp, url_prefix="/api/v1")
    for bp in (public_bp, legal_bp, auth_bp, account_bp, donor_bp, patient_bp,
               hospital_bp, admin_bp, chat_bp, security_bp, engage_bp, trust_bp, community_bp):
        app.register_blueprint(bp)

    # ------------------------------------------------------------------
    # Template helpers available on every page
    # ------------------------------------------------------------------
    @app.context_processor
    def inject_globals():
        user = current_user()
        cfg = app.config
        return {
            "csrf_token": csrf_token,
            "csp_nonce": getattr(g, "csp_nonce", ""),
            "current_user": user,
            "current_role": session.get("role"),
            "dashboard_url": dashboard_endpoint(),
            "unread_notifications": unread_count(user.id) if user and user.role == "donor" else 0,
            "chat_unread": unread_total(user.role, user.id)
            if user and user.role in ("donor", "patient", "hospital") else 0,
            "chat_open_reports": ChatReport.query.filter_by(status="Open").count()
            if user and user.role == "admin" else 0,
            "now": datetime.utcnow(),
            "t": i18n.t, "lang": i18n.current_lang(), "lang_dir": i18n.LANGUAGES[i18n.current_lang()][1],
            "languages": i18n.LANGUAGES,
            "business": {
                "name": cfg["BUSINESS_NAME"], "operator": cfg["BUSINESS_OPERATOR"],
                "address": cfg["BUSINESS_ADDRESS"], "email": cfg["BUSINESS_EMAIL"],
                "phone": cfg["BUSINESS_PHONE"], "registration": cfg["BUSINESS_REGISTRATION"],
            },
            "policy_version": cfg["POLICY_VERSION"],
            "policy_date": cfg["POLICY_EFFECTIVE_DATE"],
            "min_age": cfg["MIN_ACCOUNT_AGE"],
            "config_max_units": cfg["MAX_UNITS_PER_DONOR_DONATION"],
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
    # CSRF protection for every state-changing request
    # ------------------------------------------------------------------
    @app.before_request
    def csrf_protect():
        g.csp_nonce = secrets.token_urlsafe(16)
        if not app.config.get("WTF_CSRF_ENABLED", True):
            return
        if request.endpoint in CSRF_EXEMPT_ENDPOINTS:
            return
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken", "")
            expected = session.get("_csrf", "")
            if not expected or not hmac.compare_digest(sent, expected):
                abort(400)

    @app.after_request
    def security_headers(response):
        nonce = getattr(g, "csp_nonce", "")
        # Everything is served from this site: no CDN, analytics or ad scripts.
        response.headers.setdefault("Content-Security-Policy", (
            f"default-src 'self'; script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "form-action 'self'; frame-ancestors 'self'"))
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy",
                                    "geolocation=(self), camera=(self), microphone=(), payment=()")
        if IS_PRODUCTION:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if session.get("user_id"):
            response.headers.setdefault("Cache-Control", "no-store")   # private pages
        return response

    @app.before_request
    def housekeeping():
        expire_old_requests()

    @app.before_request
    def require_two_factor():
        """Roles listed in REQUIRE_2FA_ROLES must finish setting up 2FA before using the site."""
        role = session.get("role")
        if role and role in app.config["REQUIRE_2FA_ROLES"]:
            ep = request.endpoint or ""
            if ep.startswith(("security.", "static", "legal.")) or ep in ("auth.logout", "healthz"):
                return None
            user = current_user()
            if user is not None and not user.has_2fa:
                flash("Please turn on two-factor login to continue.", "warning")
                return redirect(url_for("security.settings"))
        return None

    @app.post("/language")
    def set_language():
        code = request.form.get("lang", "")
        if code in i18n.LANGUAGES:
            session["lang"] = code
        return redirect(i18n.safe_return_path(url_for("public.index")))

    @app.cli.command("jobs")
    @click.option("--only", multiple=True, help="expire, reminders, escalate, deliver or cleanup")
    def jobs_command(only):
        """Run the background jobs once (schedule this every 5 minutes)."""
        from utils.jobs import run_all
        for name, result in run_all(only or None).items():
            click.echo(f"{name}: {result}")

    @app.get("/healthz")
    def healthz():
        try:
            db.session.execute(text("SELECT 1"))
            return jsonify(status="ok")
        except Exception:
            return jsonify(status="database unavailable"), 503

    # ------------------------------------------------------------------
    # Error handling (no stack traces or internals are ever shown)
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

    _register_cli(app)

    with app.app_context():
        if app.config["USE_ALEMBIC"]:
            # Tables are managed by `flask db upgrade`; only seed the admin once they exist.
            if inspect(db.engine).has_table("admins"):
                _bootstrap_admin(app)
        else:
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
    """Add newly introduced columns to tables that already exist.

    ``db.create_all()`` creates missing TABLES but never adds a column to an
    existing one. This function only ever ADDS columns (nullable or with a
    default) and back-fills values; it never drops or rewrites a table, so your
    existing rows survive. For a SQLite file, a timestamped backup copy is made
    first whenever a change is needed.
    """
    engine = db.engine
    inspector = inspect(engine)
    is_sqlite = engine.dialect.name == "sqlite"
    ts = "DATETIME" if is_sqlite else "TIMESTAMP"
    false = "0" if is_sqlite else "FALSE"
    bool_t = "BOOLEAN"

    additions = {
        "donors": [("last_login_at", ts),
                   ("share_contact_consent", f"{bool_t} NOT NULL DEFAULT {false}"),
                   ("email_opt_in", f"{bool_t} NOT NULL DEFAULT {false}"),
                   ("terms_accepted_at", ts), ("age_confirmed_at", ts),
                   ("health_data_consent_at", ts), ("policy_version", "VARCHAR(20)"),
                   ("deferred_until", "DATE")],
        "patients": [("last_login_at", ts), ("terms_accepted_at", ts),
                     ("age_confirmed_at", ts), ("policy_version", "VARCHAR(20)")],
        "hospitals": [("last_login_at", ts), ("terms_accepted_at", ts),
                      ("policy_version", "VARCHAR(20)")],
        "admins": [("last_login_at", ts)],
        "blood_requests": [("closed_reason", "VARCHAR(255)"), ("closed_at", ts),
                           ("guardian_confirmed_at", ts), ("anonymised_at", ts)],
        "donation_responses": [
            ("units_pledged", "INTEGER NOT NULL DEFAULT 1"),
            ("units_collected", "INTEGER NOT NULL DEFAULT 0"),
            ("updated_at", ts), ("appointment_at", ts), ("hospital_note", "VARCHAR(255)"),
            ("contact_consent_at", ts), ("verified_at", ts),
            ("verified_by_hospital_id", "INTEGER REFERENCES hospitals(id)")],
        "notifications": [("dedupe_key", "VARCHAR(80)")],
        "chat_messages": [("kind", "VARCHAR(12) NOT NULL DEFAULT 'text'"), ("lat", "FLOAT"),
                          ("lng", "FLOAT"), ("accuracy_m", "INTEGER"), ("flag", "VARCHAR(120)")],
    }
    security = [("email_verified_at", ts), ("totp_secret", "VARCHAR(200)"), ("totp_enabled_at", ts),
                ("totp_last_step", "INTEGER"), ("recovery_codes", "TEXT")]
    additions["donors"] += [("area_lat", "FLOAT"), ("area_lng", "FLOAT"), ("available_until", ts),
                            ("sms_opt_in", f"{bool_t} NOT NULL DEFAULT {false}"),
                            ("whatsapp_opt_in", f"{bool_t} NOT NULL DEFAULT {false}")] + security
    additions["hospitals"] += [("lat", "FLOAT"), ("lng", "FLOAT")] + security
    additions["patients"] += security
    additions["admins"] += security
    additions["blood_requests"] += [("approved_at", ts), ("escalation_level", "INTEGER NOT NULL DEFAULT 0"),
                                    ("escalated_at", ts)]
    additions["donation_responses"] += [("checked_in_at", ts), ("no_show_at", ts),
                                        ("reminder_24h_at", ts), ("reminder_2h_at", ts)]
    existing_tables = set(inspector.get_table_names())
    missing = {}
    for table, columns in additions.items():
        if table in existing_tables:
            have = {c["name"] for c in inspector.get_columns(table)}
            todo = [c for c in columns if c[0] not in have]
            if todo:
                missing[table] = todo

    if not missing:
        return
    if is_sqlite and engine.url.database and os.path.exists(engine.url.database):
        backup = f"{engine.url.database}.pre-migration-{datetime.utcnow():%Y%m%d%H%M%S}.bak"
        shutil.copy2(engine.url.database, backup)
        logging.getLogger("bloodlink.migrate").info("Backed up database to %s", backup)

    backfill_status = False
    with engine.begin() as conn:
        for table, columns in missing.items():
            for name, col_type in columns:
                # PostgreSQL: IF NOT EXISTS makes this safe when two gunicorn workers
                # start at the same moment. (SQLite is development-only, one process.)
                guard = "" if is_sqlite else "IF NOT EXISTS "
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {guard}{name} {col_type}"))
        if "notifications" in missing:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_dedupe_key "
                              "ON notifications (dedupe_key)"))
        if "donation_responses" in missing:
            # Old rows that were already "Donation Completed" carried exactly one unit.
            conn.execute(text("UPDATE donation_responses SET units_collected = 1 "
                              "WHERE response_status = 'Donation Completed' AND units_collected = 0"))
            conn.execute(text("UPDATE donation_responses SET updated_at = response_date "
                              "WHERE updated_at IS NULL"))
            backfill_status = True
        if "blood_requests" in missing:
            # Requests closed by the old one-click flow have no unit records: flag them.
            conn.execute(text("UPDATE blood_requests SET closed_reason = 'legacy' "
                              "WHERE status = 'Fulfilled' AND closed_reason IS NULL"))

    if backfill_status:
        # Old "Open" requests that already have verified units become Partially Fulfilled.
        from models import BloodRequest
        from utils.allocation import recompute_status
        for req in BloodRequest.query.filter_by(status="Approved").all():
            recompute_status(req)
        db.session.commit()


def _bootstrap_admin(app):
    """Create the first administrator from ADMIN_EMAIL / ADMIN_PASSWORD."""
    email = app.config.get("ADMIN_EMAIL")
    password = app.config.get("ADMIN_PASSWORD")
    if not email or not password or Admin.query.first():
        return
    admin = Admin(name="Administrator", email=email)
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()


def _register_cli(app):
    @app.cli.command("retention-cleanup")
    def retention_cleanup_cmd():
        """Delete/anonymise data past its retention period (run daily)."""
        from utils.maintenance import retention_cleanup
        click.echo(retention_cleanup(app.config))

    @app.cli.command("check-consistency")
    def check_consistency_cmd():
        """Verify request totals agree with donation records."""
        from utils.allocation import check_consistency
        problems = check_consistency()
        click.echo("\n".join(problems) if problems else "All request totals are consistent.")
        raise SystemExit(1 if problems else 0)


app = create_app()


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="127.0.0.1", port=5000)

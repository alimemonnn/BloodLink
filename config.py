"""Application configuration for BloodLink.

The database is chosen from the environment:

* ``DATABASE_URL`` set  -> that database (PostgreSQL in production).
* ``DATABASE_URL`` not set -> a local SQLite file (development only).

That is the only thing that changes between your laptop and the live site.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

try:                                    # a .env file next to this file is read automatically (never overrides real env vars)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, ".env"))
except ImportError:                     # python-dotenv not installed: use real environment variables only
    pass

# Render sets RENDER=true. You can also set BLOODLINK_ENV=production yourself.
IS_PRODUCTION = (
    os.environ.get("BLOODLINK_ENV", "").lower() == "production"
    or os.environ.get("RENDER", "").lower() == "true"
)


def _database_uri():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return "sqlite:///" + os.path.join(BASE_DIR, "database.db")
    # Some hosts still hand out the old "postgres://" scheme, which
    # SQLAlchemy 2.x refuses. Normalise it.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _secret_key():
    key = os.environ.get("BLOODLINK_SECRET_KEY") or os.environ.get("SECRET_KEY")
    if key:
        return key
    if IS_PRODUCTION:
        # Never run a live site with a key that is public in the source code.
        raise RuntimeError("Set the SECRET_KEY environment variable in production.")
    return "bloodlink-dev-secret-key-change-me"


class Config:
    SECRET_KEY = _secret_key()

    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Cloud databases (Neon, Supabase, Render) close idle connections.
    # pre_ping checks a connection before using it, so users never get an
    # "SSL connection has been closed unexpectedly" error.
    SQLALCHEMY_ENGINE_OPTIONS = (
        {} if SQLALCHEMY_DATABASE_URI.startswith("sqlite")
        else {"pool_pre_ping": True, "pool_recycle": 280}
    )

    # Session hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = IS_PRODUCTION      # cookie only over HTTPS when live
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8   # 8 hours

    # CSRF protection for every POST form (turn off only in automated tests)
    WTF_CSRF_ENABLED = True

    # Business rules
    DONATION_GAP_DAYS = 90        # 3 months between donations
    REQUEST_VALID_DAYS = 14       # a request expires after 14 days
    ITEMS_PER_PAGE = 10
    MAX_REQUESTS_PER_HOUR = 5     # abuse prevention: posting limit per patient

    # Login brute-force protection
    LOGIN_MAX_ATTEMPTS = 5
    LOGIN_WINDOW_SECONDS = 10 * 60

    # Logged-in patients / hospitals / admins may see a donor's phone number
    # in the "Find a donor" results. Set to False to keep numbers private.
    SHOW_DONOR_CONTACT_TO_REQUESTERS = True

    # ---- Allocation rules -------------------------------------------
    # One unit per donor per donation event by default. A hospital may record
    # more only if you raise this (it must be a medically approved amount).
    MAX_UNITS_PER_DONOR_DONATION = 1
    MAX_UNITS_PER_REQUEST = 20
    MIN_ACCOUNT_AGE = 18          # donors and account holders must be adults

    # ---- Matching weights (rule-based, NOT machine learning) ----------
    # Hard medical filters are applied first; weights only order what is left.
    MATCH_WEIGHTS = {"same_city": 40, "exact_group": 20, "never_donated_or_long_rest": 10,
                     "recent_response_penalty": -15,
                     "distance_max": 30,        # points for being very close, fading to 0 at DISTANCE_FADE_KM
                     "available_now": 15,       # donor said "I can donate right now"
                     "no_show_penalty": -10}    # per recorded no-show, at most 3 counted
    DISTANCE_FADE_KM = 100

    # ---- Urgent requests that get no answer are widened automatically -----
    ESCALATION_AFTER_MINUTES = (30, 120)     # level 1 after 30 min with no offer, level 2 after 2 h
    ESCALATION_RADIUS_KM = (50, None)        # level 1 alerts donors within 50 km, level 2 everyone compatible

    # ---- Reminders for booked appointments (hours before) -----
    REMINDER_HOURS = (24, 2)

    # ---- Optional outside services. Everything below is OFF unless configured. -----
    NOTIFY_PROVIDER = os.environ.get("NOTIFY_PROVIDER", "none")      # none / log / twilio
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")
    TWILIO_SMS_FROM = os.environ.get("TWILIO_SMS_FROM", "")
    TWILIO_WHATSAPP_FROM = os.environ.get("TWILIO_WHATSAPP_FROM", "")  # e.g. whatsapp:+14155238886
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "")              # mailto:you@example.com
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    AI_MODEL = os.environ.get("AI_MODEL", "claude-haiku-5-5")
    AI_DAILY_LIMIT = int(os.environ.get("AI_DAILY_LIMIT", "60"))     # translations per person per day
    REDIS_URL = os.environ.get("REDIS_URL", "")
    SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
    LOG_FORMAT = os.environ.get("LOG_FORMAT", "text")                 # text / json
    USE_ALEMBIC = os.environ.get("USE_ALEMBIC", "") == "1"

    # ---- Account security -----
    PASSWORD_RESET_MAX_AGE = 3600                  # seconds a reset link works
    EMAIL_VERIFY_MAX_AGE = 7 * 24 * 3600
    TOTP_ISSUER = "BloodLink"
    REQUIRE_2FA_ROLES = tuple(r for r in os.environ.get("REQUIRE_2FA_ROLES", "").split(",") if r)
    DEFAULT_LANGUAGE = "en"

    # ---- Legal / business details shown in the footer and policies -----
    # Set these in the environment. Nothing here is invented: an empty value
    # is simply not displayed.
    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "BloodLink")
    BUSINESS_OPERATOR = os.environ.get("BUSINESS_OPERATOR", "Muhammad Ali (university project)")
    BUSINESS_ADDRESS = os.environ.get("BUSINESS_ADDRESS", "Sukkur, Sindh, Pakistan")
    BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "").strip()
    BUSINESS_PHONE = os.environ.get("BUSINESS_PHONE", "").strip()
    BUSINESS_REGISTRATION = os.environ.get("BUSINESS_REGISTRATION", "").strip()
    POLICY_VERSION = "2026-10-17"       # bump when a policy changes materially
    POLICY_EFFECTIVE_DATE = "17 October 2026"

    # ---- Chat (coordination between donor, patient and hospital) -----
    CHAT_MAX_LENGTH = 1000
    CHAT_RATE_LIMIT = 20          # messages ...
    CHAT_RATE_WINDOW = 60         # ... per this many seconds, per person per thread
    CHAT_RETENTION_DAYS = 90      # messages are deleted this long after the request closed
    # One-time shared locations are the most sensitive thing in a chat, so they expire quickly
    CHAT_LOCATION_VISIBLE_HOURS = 6      # coordinates stop being shown after this long
    CHAT_LOCATION_RETENTION_HOURS = 24   # and are erased from the database after this long
    CHAT_LOCATION_LIMIT = 5              # shares allowed ...
    CHAT_LOCATION_WINDOW = 600           # ... per this many seconds, per person per thread

    # ---- Data retention (applied by `flask retention-cleanup`) ---------
    CONTACT_MESSAGE_RETENTION_DAYS = 180
    CLOSED_REQUEST_ANONYMISE_DAYS = 365
    DATA_REQUEST_RETENTION_DAYS = 365
    AUDIT_LOG_RETENTION_DAYS = 730

    # ---- Optional email (in-app notifications always work without it) --
    SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
    SMTP_USER = os.environ.get("SMTP_USER", "").strip()
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM = os.environ.get("SMTP_FROM", "").strip()
    SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "").strip().lower()    # "starttls" (587, default) or "ssl" (465)
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

    # Optional: create the first admin from environment variables on startup.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


class TestingConfig(Config):
    """Used by the automated tests only: fake data, CSRF off, separate database."""
    TESTING = True
    WTF_CSRF_ENABLED = False
    ADMIN_EMAIL = None
    ADMIN_PASSWORD = None

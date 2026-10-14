"""Application configuration for BloodLink.

The database is chosen from the environment:

* ``DATABASE_URL`` set  -> that database (PostgreSQL in production).
* ``DATABASE_URL`` not set -> a local SQLite file (development only).

That is the only thing that changes between your laptop and the live site.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

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

    # Optional: create the first admin from environment variables on startup.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")

"""The optional in-process job runner (for hosts without a free cron job)."""
import threading

from conftest import make_donor
from models import OutboxMessage, db
from utils import channels, scheduler


def test_off_by_default_and_in_tests(app):
    assert scheduler.start(app) is None                       # RUN_JOBS_IN_PROCESS is off
    app.config["RUN_JOBS_IN_PROCESS"] = True
    assert scheduler.start(app) is None                       # still off while TESTING


def test_starts_a_daemon_thread_when_switched_on(app):
    app.config.update(RUN_JOBS_IN_PROCESS=True, JOBS_INTERVAL_SECONDS=3600)
    t = scheduler.start(app, force=True)
    assert isinstance(t, threading.Thread) and t.daemon and t.name == "bloodlink-jobs"


def test_one_cycle_runs_every_job(app):
    d = make_donor("O+")
    d.sms_opt_in = True
    db.session.commit()
    channels.alert_donor(d, "hello", "cycle-test")
    db.session.commit()
    result = scheduler.run_cycle(app)
    assert set(result) == {"expire", "reminders", "camps", "escalate", "deliver", "cleanup"}
    assert OutboxMessage.query.one().status == "skipped"       # queue was processed (no provider configured)


def test_a_crashing_job_never_kills_the_runner(app, monkeypatch):
    import utils.jobs as jobs
    monkeypatch.setattr(jobs, "run_all", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert scheduler.run_cycle(app) is None                    # logged, not raised


def test_database_urls_name_the_psycopg2_driver_explicitly():
    """SQLAlchemy 2.1 would otherwise pick psycopg 3 (not installed) for a plain postgresql:// address."""
    from config import normalize_db_url
    assert normalize_db_url("postgres://u:p@ep-1.neon.tech/db?sslmode=require") == \
        "postgresql+psycopg2://u:p@ep-1.neon.tech/db?sslmode=require"
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"
    assert normalize_db_url("postgresql+psycopg2://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"   # already explicit
    assert normalize_db_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"     # a deliberate choice
    assert normalize_db_url("sqlite:///x.db") == "sqlite:///x.db" and normalize_db_url("") == ""

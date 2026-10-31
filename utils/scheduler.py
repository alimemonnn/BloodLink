"""Run the background jobs inside the web process (for hosts without a free cron job).

Switch on with RUN_JOBS_IN_PROCESS=1 and keep ONE gunicorn worker (``--workers 1 --threads 4``), otherwise every
worker would run its own copy. The jobs are safe to repeat (dedupe keys), so a duplicate run only wastes time.
On a host that sleeps when idle (Render free) the jobs only run while the site is awake; use a real cron job
(``flask --app app jobs`` every 5 minutes) when you need guaranteed reminders.
"""
import logging
import threading
import time

log = logging.getLogger("bloodlink.scheduler")


def run_cycle(app):
    """One pass of every job. Never raises."""
    try:
        with app.app_context():
            from utils.jobs import run_all
            result = run_all()
        log.info("background jobs finished: %s", result)
        return result
    except Exception:
        log.exception("background jobs crashed")
        return None


def start(app, force=False):
    """Start the loop in a daemon thread. Returns the thread, or None when it is switched off."""
    if not app.config.get("RUN_JOBS_IN_PROCESS"):
        return None
    if app.config.get("TESTING") and not force:
        return None
    interval = max(60, int(app.config.get("JOBS_INTERVAL_SECONDS", 300)))

    def loop():
        time.sleep(20)                                  # let the site finish starting
        while True:
            run_cycle(app)
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="bloodlink-jobs", daemon=True)
    thread.start()
    log.info("in-process job runner started (every %s s)", interval)
    return thread

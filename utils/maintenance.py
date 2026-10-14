"""Small background housekeeping jobs run on each request cycle."""
import time
from datetime import datetime

from models import STATUS_APPROVED, STATUS_EXPIRED, STATUS_PENDING, BloodRequest, db

_last_run = 0.0
_INTERVAL_SECONDS = 60


def expire_old_requests(force=False):
    """Move open requests past their expiry date to `Expired`.

    Both Pending and Approved requests expire, so a request nobody acted on
    does not stay "Pending" forever. The check runs at most once a minute
    (it is a write query, and it should not run on every page view).
    """
    global _last_run
    now = time.time()
    if not force and now - _last_run < _INTERVAL_SECONDS:
        return 0
    _last_run = now

    stale = BloodRequest.query.filter(
        BloodRequest.status.in_([STATUS_APPROVED, STATUS_PENDING]),
        BloodRequest.expiry_date.isnot(None),
        BloodRequest.expiry_date < datetime.utcnow(),
    ).all()
    for req in stale:
        req.status = STATUS_EXPIRED
    if stale:
        db.session.commit()
    return len(stale)

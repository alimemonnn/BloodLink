"""Small housekeeping jobs run on request cycles and by the CLI."""
import time
from datetime import datetime, timedelta

from flask import current_app

from utils import chat
from models import (LIVE_STATUSES, AuditLog, BloodRequest, ContactMessage,
                    DataRequest, db)

_last_run = 0.0
_INTERVAL_SECONDS = 60


def expire_old_requests(force=False):
    """Expire live requests past their deadline (at most once a minute).

    Outstanding donor responses are cancelled and notified by
    ``allocation.expire_request``; units already confirmed stay on record.
    """
    global _last_run
    now = time.time()
    if not force and now - _last_run < _INTERVAL_SECONDS:
        return 0
    _last_run = now
    from utils.allocation import expire_request

    ids = [i for (i,) in db.session.query(BloodRequest.id).filter(
        BloodRequest.status.in_(LIVE_STATUSES),
        BloodRequest.expiry_date.isnot(None),
        BloodRequest.expiry_date < datetime.utcnow())]
    expired = sum(1 for i in ids if expire_request(i))
    # Shared locations are erased on schedule even if nobody runs the daily clean-up command.
    if chat.scrub_old_locations(current_app.config["CHAT_LOCATION_RETENTION_HOURS"]):
        db.session.commit()
    return expired


def retention_cleanup(app_config):
    """Delete or anonymise data that is past its retention period."""
    now = datetime.utcnow()
    cutoff = now - timedelta(days=app_config["CONTACT_MESSAGE_RETENTION_DAYS"])
    msgs = ContactMessage.query.filter(ContactMessage.created_at < cutoff).delete()
    dcut = now - timedelta(days=app_config["DATA_REQUEST_RETENTION_DAYS"])
    dreq = DataRequest.query.filter(DataRequest.status.in_(["Completed", "Rejected"]),
                                    DataRequest.handled_at < dcut).delete()
    audit = AuditLog.query.filter(AuditLog.created_at < now - timedelta(days=app_config["AUDIT_LOG_RETENTION_DAYS"])).delete()
    acut = now - timedelta(days=app_config["CLOSED_REQUEST_ANONYMISE_DAYS"])
    anonymised = 0
    for r in BloodRequest.query.filter(BloodRequest.closed_at.isnot(None),
                                       BloodRequest.closed_at < acut,
                                       BloodRequest.anonymised_at.is_(None)).all():
        r.patient_name, r.contact_number = "Anonymised", ""
        r.description, r.hospital_notes = None, None
        r.anonymised_at = now
        anonymised += 1
    chat_deleted = chat.delete_expired(app_config["CHAT_RETENTION_DAYS"])
    locations = chat.scrub_old_locations(app_config["CHAT_LOCATION_RETENTION_HOURS"])
    db.session.commit()
    return {"chat_messages": chat_deleted, "locations_erased": locations, "contact_messages": msgs, "data_requests": dreq, "audit_logs": audit, "requests_anonymised": anonymised}

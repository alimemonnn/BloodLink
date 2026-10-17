"""Internal (database-backed) notifications, plus optional email.

* Donors use the ``notifications`` table; patients and hospitals use
  ``account_notifications``.
* Every helper accepts a ``dedupe_key``. If a row with that key already exists
  nothing is added, so retrying an operation never produces duplicates.
* Messages never contain patient names or medical details.
"""
from models import AccountNotification, Notification, db
from utils.matching import find_matching_donors


def _exists(model, key):
    return bool(key) and db.session.query(model.id).filter_by(dedupe_key=key).first() is not None


def notify_donor(donor_id, message, request_id=None, dedupe_key=None, commit=True):
    if _exists(Notification, dedupe_key):
        return False
    db.session.add(Notification(donor_id=donor_id, message=message[:255],
                                request_id=request_id, dedupe_key=dedupe_key))
    if commit:
        db.session.commit()
    return True


def notify_account(role, user_id, message, request_id=None, dedupe_key=None, commit=True):
    """Notify a patient or hospital."""
    if _exists(AccountNotification, dedupe_key):
        return False
    db.session.add(AccountNotification(role=role, user_id=user_id, message=message[:255],
                                       request_id=request_id, dedupe_key=dedupe_key))
    if commit:
        db.session.commit()
    return True


def notify_matching_donors(blood_request):
    """Notify every donor who matches an approved request. Returns the count."""
    from utils import mailer

    donors = find_matching_donors(blood_request)
    message = (
        f"New {blood_request.blood_group_required} blood request near "
        f"{blood_request.location} ({blood_request.urgency}). "
        f"{blood_request.units_remaining} unit(s) still needed."
    )
    created = 0
    for donor in donors:
        key = f"match:{blood_request.id}:{donor.id}"
        if notify_donor(donor.id, message, blood_request.id, dedupe_key=key, commit=False):
            created += 1
    db.session.commit()
    for donor in donors:                 # email is best effort, opt-in only
        mailer.send_donor_email(donor, "A blood request needs your group", message)
    return created


def unread_count(donor_id):
    return Notification.query.filter_by(donor_id=donor_id, is_read=False).count()


def mark_all_read(donor_id):
    Notification.query.filter_by(donor_id=donor_id, is_read=False).update({"is_read": True})
    db.session.commit()


def account_updates(role, user_id, limit=8, mark_read=False):
    rows = (AccountNotification.query.filter_by(role=role, user_id=user_id)
            .order_by(AccountNotification.created_at.desc(), AccountNotification.id.desc())
            .limit(limit).all())
    if mark_read:
        unread = [r for r in rows if not r.is_read]
        for r in unread:
            r.is_read = True
        if unread:
            db.session.commit()
    return rows

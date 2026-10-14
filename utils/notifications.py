"""Internal (database-backed) notification system.

No paid SMS/email service is used. Notifications are rows in the
`notifications` table and are shown inside the donor dashboard.
"""
from models import Notification, db
from utils.matching import find_matching_donors


def notify_matching_donors(blood_request):
    """Create a notification for every donor who matches an approved request.

    Returns the number of donors notified.
    """
    donors = find_matching_donors(blood_request)
    message = (
        f"New {blood_request.blood_group_required} blood request available near "
        f"{blood_request.location} ({blood_request.urgency})."
    )
    created = 0
    for donor in donors:
        already = Notification.query.filter_by(
            donor_id=donor.id, request_id=blood_request.id
        ).first()
        if already:
            continue
        db.session.add(
            Notification(donor_id=donor.id, request_id=blood_request.id, message=message)
        )
        created += 1
    db.session.commit()
    return created


def notify_donor(donor_id, message, request_id=None):
    db.session.add(Notification(donor_id=donor_id, message=message, request_id=request_id))
    db.session.commit()


def unread_count(donor_id):
    return Notification.query.filter_by(donor_id=donor_id, is_read=False).count()


def mark_all_read(donor_id):
    Notification.query.filter_by(donor_id=donor_id, is_read=False).update({"is_read": True})
    db.session.commit()

"""Web push (browser notifications). Off until VAPID keys are set.

Generate keys once with:  python -c "from py_vapid import Vapid; v=Vapid(); v.generate_keys();
print(v.private_pem().decode()); print(v.public_key)"  (see README). Messages contain no names or
medical details, only a short generic line such as "A blood request matches your group".
"""
import json
import logging

from flask import current_app

from models import PushSubscription, db

log = logging.getLogger("bloodlink.push")


def is_configured():
    c = current_app.config
    return bool(c["VAPID_PUBLIC_KEY"] and c["VAPID_PRIVATE_KEY"] and c["VAPID_SUBJECT"])


def _webpush(subscription, payload):
    from pywebpush import webpush
    c = current_app.config
    webpush(subscription_info=subscription, data=payload, vapid_private_key=c["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": c["VAPID_SUBJECT"]}, timeout=10)


def send_to_user(role, user_id, title, body, url="/"):
    """Send to every browser the person subscribed. Returns True if at least one was reached."""
    injected = current_app.extensions.get("push_sender")
    if not (injected or is_configured()):
        raise LookupError("push not configured")
    subs = PushSubscription.query.filter_by(role=role, user_id=user_id).all()
    payload = json.dumps({"title": title[:60], "body": body[:140], "url": url})
    reached = False
    for sub in subs:
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        try:
            (injected or _webpush)(info, payload)
            reached = True
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410) or getattr(exc, "gone", False):      # browser unsubscribed
                db.session.delete(sub)
            else:
                log.warning("push to %s failed: %s", sub.id, type(exc).__name__)
    return reached

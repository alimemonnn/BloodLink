"""Optional email. In-app notifications work without any of this.

Rules this module enforces:
  * only donors who OPTED IN receive email (never pre-ticked);
  * every message carries an unsubscribe link plus List-Unsubscribe headers;
  * if SMTP or PUBLIC_BASE_URL is not configured, nothing is sent (an email
    without a working unsubscribe link is never sent);
  * a provider failure is logged and ignored, never shown as a crash.
"""
import logging
import smtplib
from email.message import EmailMessage

from flask import current_app
from itsdangerous import BadSignature, URLSafeSerializer

log = logging.getLogger("bloodlink.mail")


def _serializer():
    return URLSafeSerializer(current_app.config["SECRET_KEY"], salt="bloodlink-unsubscribe")


def unsubscribe_token(donor_id):
    return _serializer().dumps(int(donor_id))


def read_unsubscribe_token(token):
    try:
        return int(_serializer().loads(token))
    except (BadSignature, ValueError, TypeError):
        return None


def is_configured():
    c = current_app.config
    return bool(c["SMTP_HOST"] and c["SMTP_FROM"] and c["PUBLIC_BASE_URL"])


def unsubscribe_url(donor):
    return f"{current_app.config['PUBLIC_BASE_URL']}/unsubscribe/{unsubscribe_token(donor.id)}"


def build_message(donor, subject, body):
    c = current_app.config
    url = unsubscribe_url(donor)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = c["SMTP_FROM"], donor.email, subject
    msg["List-Unsubscribe"] = f"<{url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    footer = (f"\n\n--\nYou receive this because you chose email alerts on {c['BUSINESS_NAME']}.\n"
              f"Unsubscribe in one click: {url}\n{c['BUSINESS_NAME']}, {c['BUSINESS_ADDRESS']}")
    msg.set_content(body + footer)
    return msg


def send_donor_email(donor, subject, body):
    """Send one email if allowed. Returns True only if it was handed to SMTP."""
    if not (donor.email_opt_in and donor.is_active and is_configured()):
        return False
    c = current_app.config
    try:
        with smtplib.SMTP(c["SMTP_HOST"], c["SMTP_PORT"], timeout=10) as smtp:
            smtp.starttls()
            if c["SMTP_USER"]:
                smtp.login(c["SMTP_USER"], c["SMTP_PASSWORD"])
            smtp.send_message(build_message(donor, subject, body))
        return True
    except Exception as exc:                      # provider down, bad credentials...
        log.warning("email to donor %s failed: %s", donor.id, type(exc).__name__)
        return False

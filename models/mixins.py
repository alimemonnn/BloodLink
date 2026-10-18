"""Columns shared by every account type (donor, patient, hospital, admin)."""
from models import db


class SecurityMixin:
    """Optional two-factor login (TOTP) and a verified-email marker."""
    email_verified_at = db.Column(db.DateTime)
    totp_secret = db.Column(db.String(200))        # encrypted at rest, see utils/security.py
    totp_enabled_at = db.Column(db.DateTime)
    totp_last_step = db.Column(db.Integer)         # blocks re-using the same code
    recovery_codes = db.Column(db.Text)            # JSON list of hashed one-time codes

    @property
    def has_2fa(self):
        return bool(self.totp_enabled_at and self.totp_secret)

"""Tables that support privacy, consent and accountability."""
from datetime import datetime

from models import db


class ConsentRecord(db.Model):
    """Proof of what a person agreed to, when, and under which policy version."""
    __tablename__ = "consent_records"
    id = db.Column(db.Integer, primary_key=True)
    subject_role = db.Column(db.String(20), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    purpose = db.Column(db.String(40), nullable=False)   # terms_privacy, health_data, contact_sharing, age_18, email_notifications
    granted = db.Column(db.Boolean, nullable=False, default=True)
    policy_version = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.Index("ix_consent_subject", "subject_role", "subject_id"),)


class ContactMessage(db.Model):
    """Messages sent through the contact form (previously they were discarded)."""
    __tablename__ = "contact_messages"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120))
    message = db.Column(db.Text, nullable=False)
    handled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class DataRequest(db.Model):
    """A request to access, correct or erase personal data (works without an account)."""
    __tablename__ = "data_requests"
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)       # delete / access / correct
    name = db.Column(db.String(120))
    email = db.Column(db.String(120), nullable=False)
    details = db.Column(db.Text)
    status = db.Column(db.String(20), default="Open", index=True)   # Open / In progress / Completed / Rejected
    admin_note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    handled_at = db.Column(db.DateTime)


class AccountNotification(db.Model):
    """In-app notifications for patients and hospitals (donors use Notification)."""
    __tablename__ = "account_notifications"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("blood_requests.id"), nullable=True)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    dedupe_key = db.Column(db.String(80), unique=True)
    __table_args__ = (db.Index("ix_acctnotif_user", "role", "user_id"),)


class AuditLog(db.Model):
    """Who did what to which record. Never stores passwords or medical detail."""
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    actor_role = db.Column(db.String(20))
    actor_id = db.Column(db.Integer)
    action = db.Column(db.String(60), nullable=False)
    target_type = db.Column(db.String(40))
    target_id = db.Column(db.Integer)
    detail = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

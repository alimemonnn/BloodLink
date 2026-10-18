"""Tables added for alerts, push, blood stock and donation camps."""
from datetime import datetime

from models import db


class OutboxMessage(db.Model):
    """One SMS / WhatsApp / email waiting to be sent by the background job."""
    __tablename__ = "outbox"
    id = db.Column(db.Integer, primary_key=True)
    channel = db.Column(db.String(12), nullable=False, index=True)      # sms / whatsapp / email
    role = db.Column(db.String(12), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    to_address = db.Column(db.String(160), nullable=False)
    subject = db.Column(db.String(160))
    body = db.Column(db.String(600), nullable=False)
    status = db.Column(db.String(12), default="pending", index=True)    # pending / sent / failed / skipped
    attempts = db.Column(db.Integer, default=0)
    last_error = db.Column(db.String(120))
    dedupe_key = db.Column(db.String(100), unique=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at = db.Column(db.DateTime)


class PushSubscription(db.Model):
    """A browser the person allowed to receive push notifications."""
    __tablename__ = "push_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(12), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    endpoint = db.Column(db.String(600), unique=True, nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.Index("ix_push_owner", "role", "user_id"),)


class BloodStock(db.Model):
    """Units a hospital says it holds, per blood group (self-reported)."""
    __tablename__ = "blood_stock"
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    blood_group = db.Column(db.String(3), nullable=False)
    units = db.Column(db.Integer, nullable=False, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    hospital = db.relationship("Hospital", backref=db.backref("stock", cascade="all, delete-orphan"))
    __table_args__ = (db.UniqueConstraint("hospital_id", "blood_group", name="uq_stock_group"),)


class Camp(db.Model):
    """A blood donation camp run by a hospital."""
    __tablename__ = "camps"
    id = db.Column(db.Integer, primary_key=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    title = db.Column(db.String(140), nullable=False)
    venue = db.Column(db.String(200), nullable=False)
    city = db.Column(db.String(80), nullable=False, index=True)
    starts_at = db.Column(db.DateTime, nullable=False, index=True)
    ends_at = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, nullable=False, default=50)
    description = db.Column(db.String(600))
    is_cancelled = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    hospital = db.relationship("Hospital", backref=db.backref("camps", cascade="all, delete-orphan"))
    signups = db.relationship("CampSignup", backref="camp", cascade="all, delete-orphan")

    @property
    def spots_left(self):
        return max(0, self.capacity - len(self.signups))


class CampSignup(db.Model):
    __tablename__ = "camp_signups"
    id = db.Column(db.Integer, primary_key=True)
    camp_id = db.Column(db.Integer, db.ForeignKey("camps.id"), nullable=False)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    donor = db.relationship("Donor", backref=db.backref("camp_signups", cascade="all, delete-orphan"))
    __table_args__ = (db.UniqueConstraint("camp_id", "donor_id", name="uq_camp_donor"),)

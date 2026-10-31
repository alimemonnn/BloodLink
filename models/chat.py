"""In-app chat between the people working on one donor offer.

One thread = one ``DonationResponse`` (one donor, one request). The donor, the
patient who posted the request and the hospital that owns it are the only
participants; an admin can read a thread only after somebody reported it.

Chat is coordination only. It never changes a request's status and it can
never count blood: only a hospital confirming a donation does that.
"""
from datetime import datetime

from models import db


class ChatMessage(db.Model):
    __tablename__ = "chat_messages"
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey("donation_responses.id"),
                            nullable=False, index=True)
    sender_role = db.Column(db.String(20), nullable=False)      # donor / patient / hospital / system
    sender_id = db.Column(db.Integer, nullable=False)
    body = db.Column(db.String(1000), nullable=False)
    # text = typed by a person, event = automatic timeline line, location = one-time shared position
    kind = db.Column(db.String(12), nullable=False, default="text", server_default="text")
    lat = db.Column(db.Float)
    lng = db.Column(db.Float)
    accuracy_m = db.Column(db.Integer)
    flag = db.Column(db.String(120))          # why the message looked like a money request, if it did
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    response = db.relationship(
        "DonationResponse",
        backref=db.backref("chat_messages", cascade="all, delete-orphan", lazy=True))

    __table_args__ = (db.Index("ix_chat_thread_order", "response_id", "id"),)


class ChatRead(db.Model):
    """The newest message each participant has seen in a thread (for unread badges)."""
    __tablename__ = "chat_reads"
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey("donation_responses.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    last_read_id = db.Column(db.Integer, nullable=False, default=0)

    response = db.relationship(
        "DonationResponse",
        backref=db.backref("chat_reads", cascade="all, delete-orphan", lazy=True))

    __table_args__ = (db.UniqueConstraint("response_id", "role", "user_id", name="uq_chat_read"),)


class ChatReport(db.Model):
    """A participant flags a thread (or one message) for an administrator."""
    __tablename__ = "chat_reports"
    id = db.Column(db.Integer, primary_key=True)
    response_id = db.Column(db.Integer, db.ForeignKey("donation_responses.id"),
                            nullable=False, index=True)
    message_id = db.Column(db.Integer)                           # optional; plain int on purpose
    reporter_role = db.Column(db.String(20), nullable=False)
    reporter_id = db.Column(db.Integer, nullable=False)
    reason = db.Column(db.String(300), nullable=False)
    status = db.Column(db.String(20), default="Open", index=True)   # Open / Dismissed / Thread locked
    admin_note = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    handled_at = db.Column(db.DateTime)

    response = db.relationship(
        "DonationResponse",
        backref=db.backref("chat_reports", cascade="all, delete-orphan", lazy=True))

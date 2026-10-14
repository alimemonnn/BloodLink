"""Blood request, donor response and notification models."""
from datetime import datetime, timedelta

from models import db

# ----------------------------------------------------------------------
# Request status values used across the whole application
# ----------------------------------------------------------------------
STATUS_PENDING = "Pending Hospital Approval"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"
STATUS_FULFILLED = "Fulfilled"
STATUS_EXPIRED = "Expired"

ALL_STATUSES = [STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED,
                STATUS_FULFILLED, STATUS_EXPIRED]

URGENCY_LEVELS = ["Normal", "Urgent", "Critical"]

# Bootstrap colour used for each status badge
STATUS_COLORS = {
    STATUS_PENDING: "warning",
    STATUS_APPROVED: "primary",
    STATUS_REJECTED: "secondary",
    STATUS_FULFILLED: "success",
    STATUS_EXPIRED: "dark",
}

URGENCY_COLORS = {"Normal": "info", "Urgent": "warning", "Critical": "danger"}


class BloodRequest(db.Model):
    __tablename__ = "blood_requests"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)

    patient_name = db.Column(db.String(120), nullable=False)
    blood_group_required = db.Column(db.String(3), nullable=False, index=True)
    units_required = db.Column(db.Integer, default=1)
    urgency = db.Column(db.String(20), default="Normal")
    location = db.Column(db.String(160), nullable=False)   # hospital location / city
    contact_number = db.Column(db.String(30), nullable=False)
    description = db.Column(db.Text)

    status = db.Column(db.String(40), default=STATUS_PENDING, index=True)
    hospital_verified = db.Column(db.Boolean, default=False)
    hospital_notes = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expiry_date = db.Column(db.DateTime)

    responses = db.relationship(
        "DonationResponse", backref="request", lazy=True, cascade="all, delete-orphan"
    )
    notifications = db.relationship(
        "Notification", backref="request", lazy=True, cascade="all, delete-orphan"
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if self.expiry_date is None:
            self.expiry_date = datetime.utcnow() + timedelta(days=14)

    # ------------------------------------------------------------------
    # Helpers used by templates
    # ------------------------------------------------------------------
    @property
    def status_color(self):
        return STATUS_COLORS.get(self.status, "secondary")

    @property
    def urgency_color(self):
        return URGENCY_COLORS.get(self.urgency, "secondary")

    @property
    def is_editable(self):
        """Patients may only edit a request while the hospital has not acted."""
        return self.status == STATUS_PENDING

    @property
    def is_visible_to_donors(self):
        return self.status == STATUS_APPROVED and not self.has_expired

    @property
    def has_expired(self):
        return bool(self.expiry_date and self.expiry_date < datetime.utcnow())

    @property
    def response_count(self):
        return len(self.responses)

    def __repr__(self):
        return f"<BloodRequest #{self.id} {self.blood_group_required} {self.status}>"


class DonationResponse(db.Model):
    """A donor saying 'I can donate' against a specific request."""

    __tablename__ = "donation_responses"
    # A donor can only respond once per request (enforced at DB level too).
    __table_args__ = (db.UniqueConstraint("donor_id", "request_id", name="uq_donor_request"),)

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id"), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("blood_requests.id"), nullable=False)
    response_status = db.Column(db.String(30), default="Interested")
    response_date = db.Column(db.DateTime, default=datetime.utcnow)
    donation_date = db.Column(db.Date, nullable=True)

    @property
    def status_color(self):
        return {
            "Interested": "info",
            "Contacted": "primary",
            "Donation Completed": "success",
            "Cancelled": "secondary",
        }.get(self.response_status, "secondary")

    def __repr__(self):
        return f"<DonationResponse donor={self.donor_id} request={self.request_id}>"


class Notification(db.Model):
    """In-app notification stored in the database (no paid SMS/email service)."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id"), nullable=False)
    request_id = db.Column(db.Integer, db.ForeignKey("blood_requests.id"), nullable=True)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Notification donor={self.donor_id}>"

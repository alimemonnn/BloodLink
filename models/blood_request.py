"""Blood request, donor response (= one donor's contribution) and notifications.

Multi-donor design (the "3 units, 3 donors" scenario)
-----------------------------------------------------
* A BloodRequest says how many units are *required*.
* Each donor who offers help gets ONE DonationResponse row for that request.
* Only a hospital can turn a response into a confirmed donation, which sets
  ``units_collected`` on that row.
* Request totals are DERIVED from those rows (see the properties below), so
  there is no stored counter that can drift out of sync.
"""
from datetime import datetime, timedelta

from models import db

# ----------------------------------------------------------------------
# Request status values (the stored strings stay compatible with old data)
# ----------------------------------------------------------------------
STATUS_PENDING = "Pending Hospital Approval"
STATUS_APPROVED = "Approved"            # shown to users as "Open"
STATUS_PARTIAL = "Partially Fulfilled"
STATUS_REJECTED = "Rejected"
STATUS_FULFILLED = "Fulfilled"
STATUS_CANCELLED = "Cancelled"
STATUS_EXPIRED = "Expired"

ALL_STATUSES = [STATUS_PENDING, STATUS_APPROVED, STATUS_PARTIAL, STATUS_FULFILLED,
                STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED]
OPEN_STATUSES = (STATUS_APPROVED, STATUS_PARTIAL)       # donors may respond
LIVE_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_PARTIAL)
CLOSED_STATUSES = (STATUS_FULFILLED, STATUS_REJECTED, STATUS_CANCELLED, STATUS_EXPIRED)

STATUS_LABELS = {STATUS_APPROVED: "Open"}
STATUS_COLORS = {
    STATUS_PENDING: "warning", STATUS_APPROVED: "primary", STATUS_PARTIAL: "info",
    STATUS_REJECTED: "secondary", STATUS_FULFILLED: "success",
    STATUS_CANCELLED: "secondary", STATUS_EXPIRED: "dark",
}
URGENCY_LEVELS = ["Normal", "Urgent", "Critical"]
URGENCY_COLORS = {"Normal": "info", "Urgent": "warning", "Critical": "danger"}

# ----------------------------------------------------------------------
# Donor-response states. None of these, except "Donation Completed" set by
# a hospital, means blood has actually been collected.
# ----------------------------------------------------------------------
RESP_INTERESTED = "Interested"
RESP_CONTACTED = "Contacted"
RESP_SCHEDULED = "Appointment Scheduled"
RESP_COMPLETED = "Donation Completed"
RESP_CANCELLED = "Cancelled"
RESP_INELIGIBLE = "Ineligible"
ACTIVE_RESPONSES = (RESP_INTERESTED, RESP_CONTACTED, RESP_SCHEDULED)
RESPONSE_COLORS = {
    RESP_INTERESTED: "info", RESP_CONTACTED: "primary", RESP_SCHEDULED: "primary",
    RESP_COMPLETED: "success", RESP_CANCELLED: "secondary", RESP_INELIGIBLE: "dark",
}


class BloodRequest(db.Model):
    __tablename__ = "blood_requests"
    __table_args__ = (
        db.CheckConstraint("units_required >= 1", name="ck_request_units_positive"),
    )

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)

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
    expiry_date = db.Column(db.DateTime)                    # the "required by" deadline

    # Added in the multi-donor upgrade (nullable, so old rows stay valid)
    closed_reason = db.Column(db.String(255))
    closed_at = db.Column(db.DateTime)
    approved_at = db.Column(db.DateTime)
    escalation_level = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    escalated_at = db.Column(db.DateTime)
    guardian_confirmed_at = db.Column(db.DateTime)          # request made for a minor
    anonymised_at = db.Column(db.DateTime)                  # personal data scrubbed

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
    # Progress -- always computed from the donation records
    # ------------------------------------------------------------------
    @property
    def required(self):
        try:
            return max(0, int(self.units_required or 0))
        except (TypeError, ValueError):
            return 0

    @property
    def units_confirmed(self):
        """Units a hospital has verified as collected."""
        return sum((r.units_collected or 0) for r in self.responses
                   if r.response_status == RESP_COMPLETED)

    @property
    def units_pledged(self):
        """Units promised by donors who have NOT yet been verified."""
        return sum((r.units_pledged or 0) for r in self.responses
                   if r.response_status in ACTIVE_RESPONSES)

    @property
    def units_remaining(self):
        return max(0, self.required - self.units_confirmed)

    @property
    def progress_percent(self):
        if self.required <= 0:
            return 0
        return int(min(100, self.units_confirmed / self.required * 100))

    @property
    def active_response_count(self):
        return sum(1 for r in self.responses if r.response_status in ACTIVE_RESPONSES)

    # ------------------------------------------------------------------
    # Helpers used by templates
    # ------------------------------------------------------------------
    @property
    def status_label(self):
        return STATUS_LABELS.get(self.status, self.status)

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
    def is_open(self):
        return self.status in OPEN_STATUSES and not self.has_expired

    @property
    def is_live(self):
        return self.status in LIVE_STATUSES

    @property
    def is_visible_to_donors(self):
        return self.is_open

    @property
    def has_expired(self):
        return bool(self.expiry_date and self.expiry_date < datetime.utcnow())

    @property
    def response_count(self):
        return len(self.responses)

    @property
    def public_label(self):
        """Initials only: the public board never shows a patient's name."""
        parts = [p for p in (self.patient_name or "").split() if p]
        return " ".join(p[0].upper() + "." for p in parts[:2]) or "Patient"

    def __repr__(self):
        return f"<BloodRequest #{self.id} {self.blood_group_required} {self.status}>"


class DonationResponse(db.Model):
    """One donor's offer / contribution against one request.

    ``response_status`` says where the offer is; ``units_collected`` is only
    ever filled in by a hospital, together with ``verified_by_hospital_id``
    and ``verified_at``.
    """

    __tablename__ = "donation_responses"
    # One row per donor per request. A donor who cancelled may re-open the SAME
    # row while the request is still open, so the pair stays unique forever.
    __table_args__ = (
        db.UniqueConstraint("donor_id", "request_id", name="uq_donor_request"),
        db.CheckConstraint("units_pledged >= 1", name="ck_response_pledged_positive"),
        db.CheckConstraint("units_collected >= 0", name="ck_response_collected_nonneg"),
    )

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id"), nullable=False, index=True)
    request_id = db.Column(db.Integer, db.ForeignKey("blood_requests.id"), nullable=False, index=True)
    response_status = db.Column(db.String(30), default=RESP_INTERESTED, index=True)
    response_date = db.Column(db.DateTime, default=datetime.utcnow)
    donation_date = db.Column(db.Date, nullable=True)

    units_pledged = db.Column(db.Integer, nullable=False, default=1, server_default="1")
    units_collected = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    appointment_at = db.Column(db.DateTime)
    checked_in_at = db.Column(db.DateTime)           # donor arrived and the hospital scanned the code
    no_show_at = db.Column(db.DateTime)              # hospital recorded that the donor did not come
    reminder_24h_at = db.Column(db.DateTime)
    reminder_2h_at = db.Column(db.DateTime)
    hospital_note = db.Column(db.String(255))
    contact_consent_at = db.Column(db.DateTime)             # donor agreed to share contact
    verified_by_hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"))
    verified_at = db.Column(db.DateTime)

    verified_by = db.relationship("Hospital", foreign_keys=[verified_by_hospital_id])

    @property
    def is_active(self):
        return self.response_status in ACTIVE_RESPONSES

    @property
    def status_color(self):
        return RESPONSE_COLORS.get(self.response_status, "secondary")

    def __repr__(self):
        return f"<DonationResponse donor={self.donor_id} request={self.request_id}>"


class Notification(db.Model):
    """In-app notification for a donor (no paid SMS/email service needed)."""

    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id"), nullable=False, index=True)
    request_id = db.Column(db.Integer, db.ForeignKey("blood_requests.id"), nullable=True)
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Same operation retried => same key => no duplicate row.
    dedupe_key = db.Column(db.String(80), unique=True)

    def __repr__(self):
        return f"<Notification donor={self.donor_id}>"

"""Donor model, including donation eligibility rules."""
from datetime import date, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from models import db
from models.mixins import SecurityMixin

# A donor must wait this many days between two whole-blood donations (~3 months)
DONATION_GAP_DAYS = 90


class Donor(SecurityMixin, db.Model):
    __tablename__ = "donors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    blood_group = db.Column(db.String(3), nullable=False, index=True)
    city = db.Column(db.String(80), nullable=False, index=True)
    area = db.Column(db.String(120))
    last_donation_date = db.Column(db.Date, nullable=True)
    availability = db.Column(db.String(20), default="Available")   # Available / Not Available
    eligibility_status = db.Column(db.String(20), default="Eligible")  # Eligible / Not Eligible
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # Consent and privacy (added in the compliance upgrade; all nullable/defaulted)
    share_contact_consent = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    email_opt_in = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    terms_accepted_at = db.Column(db.DateTime)
    age_confirmed_at = db.Column(db.DateTime)
    health_data_consent_at = db.Column(db.DateTime)
    policy_version = db.Column(db.String(20))
    # Set only by a hospital after screening; matching skips the donor until then.
    deferred_until = db.Column(db.Date)
    # Optional, rounded to about 1 km. Used only to rank nearby requests.
    area_lat = db.Column(db.Float)
    area_lng = db.Column(db.Float)
    available_until = db.Column(db.DateTime)      # "I can donate right now" window
    sms_opt_in = db.Column(db.Boolean, nullable=False, default=False, server_default="0")
    whatsapp_opt_in = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    responses = db.relationship(
        "DonationResponse", backref="donor", lazy=True, cascade="all, delete-orphan"
    )
    notifications = db.relationship(
        "Notification", backref="donor", lazy=True, cascade="all, delete-orphan"
    )

    # ------------------------------------------------------------------
    # Passwords
    # ------------------------------------------------------------------
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role(self):
        return "donor"

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    @property
    def is_eligible(self):
        """Interval check ONLY: never donated, or the configured gap has passed.

        This is a screening aid, not a medical decision. A hospital makes the
        real eligibility decision (and may defer a donor via ``deferred_until``).
        """
        if self.last_donation_date is None:
            return True
        return (date.today() - self.last_donation_date).days >= DONATION_GAP_DAYS

    @property
    def next_eligible_date(self):
        if self.last_donation_date is None:
            return None
        return self.last_donation_date + timedelta(days=DONATION_GAP_DAYS)

    @property
    def days_until_eligible(self):
        if self.is_eligible:
            return 0
        return (self.next_eligible_date - date.today()).days

    def refresh_eligibility(self):
        """Keep the stored eligibility column in sync with the computed value."""
        self.eligibility_status = "Eligible" if self.is_eligible else "Not Eligible"
        return self.eligibility_status

    @property
    def is_matchable(self):
        """Only active, available and eligible donors take part in matching."""
        deferred = self.deferred_until is not None and self.deferred_until > date.today()
        return (bool(self.is_active) and self.availability == "Available"
                and self.is_eligible and not deferred)

    @property
    def completed_donations(self):
        return sum(1 for r in self.responses if r.response_status == "Donation Completed")

    def __repr__(self):
        return f"<Donor {self.name} {self.blood_group}>"

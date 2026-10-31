"""Hospital screening reports that a donor may read.

This is health data. It is written only by the hospital that did the screening, readable only by that hospital and
by the donor it is about (when the hospital shares it), and never shown to patients, other donors or administrators.
BloodLink does NOT carry infectious-disease test results: hospitals share those in person.
"""
from datetime import datetime

from models import db

OUTCOMES = ("Fit to donate", "Temporarily deferred", "Not eligible")
REASONS = ("Low haemoglobin", "Blood pressure", "Low weight", "Recent illness or fever", "Taking medication",
           "Recent surgery, tattoo or piercing", "Recent travel", "Pregnancy or breastfeeding",
           "Recent donation", "Other (see message)")


class ScreeningReport(db.Model):
    __tablename__ = "screening_reports"
    id = db.Column(db.Integer, primary_key=True)
    # exactly one of these two says what the screening was for
    response_id = db.Column(db.Integer, db.ForeignKey("donation_responses.id"), unique=True)
    camp_signup_id = db.Column(db.Integer, db.ForeignKey("camp_signups.id"), unique=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id"), nullable=False, index=True)
    hospital_id = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False, index=True)
    outcome = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.String(60))
    deferral_until = db.Column(db.Date)
    hemoglobin = db.Column(db.Float)          # g/dL
    systolic = db.Column(db.Integer)          # mmHg
    diastolic = db.Column(db.Integer)
    pulse = db.Column(db.Integer)             # beats per minute
    temperature_c = db.Column(db.Float)
    weight_kg = db.Column(db.Float)
    message_to_donor = db.Column(db.String(600))
    internal_note = db.Column(db.String(600))   # hospital only: never shown to the donor or anyone else
    shared_with_donor = db.Column(db.Boolean, nullable=False, default=True, server_default="1")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    donor = db.relationship("Donor", backref=db.backref("screening_reports", cascade="all, delete-orphan"))
    hospital = db.relationship("Hospital")
    response = db.relationship("DonationResponse", backref=db.backref("screening_report", uselist=False,
                                                                       cascade="all, delete-orphan"))
    camp_signup = db.relationship("CampSignup", backref=db.backref("screening_report", uselist=False,
                                                                    cascade="all, delete-orphan"))

    @property
    def fit(self):
        return self.outcome == OUTCOMES[0]

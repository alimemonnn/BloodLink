"""Hospital model."""
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from models import db


class Hospital(db.Model):
    __tablename__ = "hospitals"

    id = db.Column(db.Integer, primary_key=True)
    hospital_name = db.Column(db.String(160), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False)
    address = db.Column(db.String(255))
    city = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    # is_verified: approved by an admin. Unverified hospitals cannot log in.
    is_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)
    terms_accepted_at = db.Column(db.DateTime)
    policy_version = db.Column(db.String(20))

    requests = db.relationship("BloodRequest", backref="hospital", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role(self):
        return "hospital"

    @property
    def name(self):
        """Uniform attribute so templates can use `current_user.name`."""
        return self.hospital_name

    def __repr__(self):
        return f"<Hospital {self.hospital_name}>"

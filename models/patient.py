"""Patient / requester model."""
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from models import db


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(80), nullable=False)
    address = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    requests = db.relationship(
        "BloodRequest", backref="patient", lazy=True, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def role(self):
        return "patient"

    def count_by_status(self, status):
        return sum(1 for r in self.requests if r.status == status)

    def __repr__(self):
        return f"<Patient {self.email}>"

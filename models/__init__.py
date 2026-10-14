"""SQLAlchemy models for BloodLink.

`db` is created here and imported by every model module, which keeps the
models decoupled from the Flask application object (application factory
pattern).
"""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

# Imported after `db` exists so the model modules can do `from models import db`.
from .user import Admin              # noqa: E402,F401
from .donor import Donor             # noqa: E402,F401
from .patient import Patient         # noqa: E402,F401
from .hospital import Hospital       # noqa: E402,F401
from .blood_request import (         # noqa: E402,F401
    BloodRequest,
    DonationResponse,
    Notification,
    STATUS_PENDING,
    STATUS_APPROVED,
    STATUS_REJECTED,
    STATUS_FULFILLED,
    STATUS_EXPIRED,
)

__all__ = [
    "db", "Admin", "Donor", "Patient", "Hospital", "BloodRequest",
    "DonationResponse", "Notification", "STATUS_PENDING", "STATUS_APPROVED",
    "STATUS_REJECTED", "STATUS_FULFILLED", "STATUS_EXPIRED",
]

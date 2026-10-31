"""CNIC (national ID) verification record for a donor.

One row per donor. The ID image is stored ENCRYPTED in the database (see utils/cnic.py), never in a
public folder. Only an administrator can open it. A donor whose record is ``Approved`` gets the
"Verified donor" badge; a donor without an approved record can still donate, just without the badge.
"""
from datetime import datetime

from models import db

CNIC_PENDING = "Pending"
CNIC_APPROVED = "Approved"
CNIC_REJECTED = "Rejected"
CNIC_INCOMPLETE = "Incomplete"    # number typed at registration, image not uploaded yet
CNIC_STATUSES = (CNIC_INCOMPLETE, CNIC_PENDING, CNIC_APPROVED, CNIC_REJECTED)


class DonorCNIC(db.Model):
    __tablename__ = "donor_cnic"

    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey("donors.id"), nullable=False, unique=True, index=True)
    cnic_number = db.Column(db.String(15), nullable=False, unique=True)    # 12345-1234567-1
    file_data = db.Column(db.LargeBinary, nullable=False)                  # encrypted image / PDF
    file_mime = db.Column(db.String(40), nullable=False)
    status = db.Column(db.String(12), nullable=False, default=CNIC_PENDING, index=True)
    reject_reason = db.Column(db.String(255))
    submitted_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_admin_id = db.Column(db.Integer)

    # ``donor.cnic`` gives the record (or None) without editing the Donor model file.
    donor = db.relationship(
        "Donor", backref=db.backref("cnic", uselist=False, cascade="all, delete-orphan"))

    @property
    def is_approved(self):
        return self.status == CNIC_APPROVED

    @property
    def has_file(self):
        return bool(self.file_data)

    @property
    def masked_number(self):
        """12345-1234567-1 -> *****-***4567-1 (what the donor sees about themselves)."""
        n = self.cnic_number or ""
        return f"*****-***{n[9:13]}-{n[14:]}" if len(n) == 15 else "*****"

    def __repr__(self):
        return f"<DonorCNIC donor={self.donor_id} {self.status}>"

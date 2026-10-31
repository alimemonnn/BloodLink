"""CNIC helpers: number check, file check, encryption at rest, saving a submission.

* A Pakistani CNIC has 13 digits, written 12345-1234567-1. Dashes are optional when typing.
* The file must really be a JPEG, PNG or PDF (checked by its first bytes, not its name) and at most
  ``CNIC_MAX_BYTES``.
* The file is encrypted with a key derived from SECRET_KEY before it is stored.
"""
import base64
import hashlib
import re
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from models import db
from models.cnic import CNIC_APPROVED, CNIC_INCOMPLETE, CNIC_PENDING, DonorCNIC

CNIC_MAX_BYTES = 3 * 1024 * 1024
_SIGNATURES = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
)


def normalise_number(raw):
    """Return '12345-1234567-1' or None when the input is not a plausible CNIC."""
    digits = re.sub(r"[\s-]", "", raw or "")
    if not re.fullmatch(r"\d{13}", digits) or len(set(digits)) == 1 or digits[0] == "0":
        return None
    return f"{digits[:5]}-{digits[5:12]}-{digits[12]}"


def detect_mime(data):
    for magic, mime in _SIGNATURES:
        if data.startswith(magic):
            return mime
    return None


def read_upload(storage):
    """Return (bytes, mime, error). ``storage`` is a werkzeug FileStorage (or None)."""
    if storage is None or not storage.filename:
        return None, None, None                       # nothing uploaded
    data = storage.stream.read(CNIC_MAX_BYTES + 1)
    if not data:
        return None, None, "The CNIC file is empty."
    if len(data) > CNIC_MAX_BYTES:
        return None, None, f"The CNIC file must be {CNIC_MAX_BYTES // (1024 * 1024)} MB or smaller."
    mime = detect_mime(data)
    if mime is None:
        return None, None, "Upload the CNIC as a JPG, PNG or PDF file."
    return data, mime, None


def _fernet():
    key = hashlib.sha256(("cnic|" + current_app.config["SECRET_KEY"]).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(data):
    return _fernet().encrypt(data)


def unseal(blob):
    """Decrypted bytes, or None when the key changed or the data is damaged."""
    try:
        return _fernet().decrypt(bytes(blob))
    except (InvalidToken, TypeError, ValueError):
        return None


def validate_submission(form, files, donor=None, required=False):
    """Check the CNIC part of a form.

    Returns ``(errors, number, data, mime)``. When nothing was entered and ``required`` is False the
    result is ``([], None, None, None)``: the donor simply registers without a CNIC.
    """
    raw = (form.get("cnic_number") or "").strip()
    data, mime, file_error = read_upload(files.get("cnic_file"))
    if not raw and data is None and file_error is None and not required:
        return [], None, None, None

    errors = []
    number = normalise_number(raw)
    if not raw:
        errors.append("Enter your CNIC number (13 digits).")
    elif number is None:
        errors.append("The CNIC number must be 13 digits, for example 42101-1234567-1.")
    if file_error:
        errors.append(file_error)
    elif data is None:
        errors.append("Upload a clear photo or scan of your CNIC (JPG, PNG or PDF).")
    if number:
        other = DonorCNIC.query.filter_by(cnic_number=number).first()
        if other is not None and (donor is None or other.donor_id != donor.id):
            errors.append("This CNIC number is already linked to another account.")
    if form.get("cnic_consent") not in ("on", "1", "true", "yes"):
        errors.append("Please tick the box that allows BloodLink to store your CNIC for verification.")
    return errors, number, data, mime


def validate_number(raw, donor=None):
    """Check only the CNIC number (used at registration). Returns ``(errors, number)``; empty is allowed."""
    raw = (raw or "").strip()
    if not raw:
        return [], None
    number = normalise_number(raw)
    if number is None:
        return ["The CNIC number must be 13 digits, for example 42101-1234567-1."], None
    other = DonorCNIC.query.filter_by(cnic_number=number).first()
    if other is not None and (donor is None or other.donor_id != donor.id):
        return ["This CNIC number is already linked to another account."], None
    return [], number


def save_number(donor, number):
    """Keep the number typed at registration; the image is added later (does not commit)."""
    record = DonorCNIC(donor_id=donor.id, cnic_number=number, file_data=b"", file_mime="",
                       status=CNIC_INCOMPLETE)
    db.session.add(record)
    return record


def save_submission(donor, number, data, mime):
    """Create or replace the donor's record as Pending (does not commit)."""
    record = donor.cnic or DonorCNIC(donor_id=donor.id)
    record.cnic_number = number
    record.file_data = seal(data)
    record.file_mime = mime
    record.status = CNIC_PENDING
    record.reject_reason = None
    record.submitted_at = datetime.utcnow()
    record.reviewed_at = None
    record.reviewed_by_admin_id = None
    if record.id is None:
        db.session.add(record)
    return record


def is_verified(donor):
    return bool(donor is not None and donor.cnic is not None and donor.cnic.status == CNIC_APPROVED)

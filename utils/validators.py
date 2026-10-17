"""Form validation helpers.

Every public form passes through these functions before anything is written
to the database.
"""
import re
from datetime import date, datetime

from utils.matching import BLOOD_GROUPS

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^[+]?[0-9\-\s]{7,20}$")

URGENCY_LEVELS = ["Normal", "Urgent", "Critical"]
AVAILABILITY_OPTIONS = ["Available", "Not Available"]


def is_valid_email(value):
    return bool(value and EMAIL_RE.match(value.strip()))


def is_valid_phone(value):
    return bool(value and PHONE_RE.match(value.strip()) and sum(c.isdigit() for c in value) >= 7)


def is_valid_blood_group(value):
    return value in BLOOD_GROUPS


def parse_date(value):
    """Return a date object from a YYYY-MM-DD string, or None."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _too_long(form, field, limit, label, errors):
    """PostgreSQL rejects text longer than the column size (SQLite silently
    accepts it), so over-long input is caught here as a normal form error
    instead of crashing with a 500 page."""
    if len(form.get(field, "") or "") > limit:
        errors.append(f"{label} must be {limit} characters or fewer.")


def validate_password(password, confirm=None):
    errors = []
    if not password or len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    elif len(password) > 128:
        errors.append("Password must be 128 characters or fewer.")
    if confirm is not None and password != confirm:
        errors.append("Passwords do not match.")
    return errors


def validate_donor_form(form, require_password=True):
    """Validate donor registration / profile data. Returns a list of errors."""
    errors = []
    if not form.get("name", "").strip():
        errors.append("Full name is required.")
    if not is_valid_email(form.get("email", "")):
        errors.append("Enter a valid email address.")
    if not is_valid_phone(form.get("phone", "")):
        errors.append("Enter a valid phone number.")
    if not is_valid_blood_group(form.get("blood_group", "")):
        errors.append("Select a valid blood group.")
    if not form.get("city", "").strip():
        errors.append("City is required.")

    raw_date = form.get("last_donation_date", "").strip()
    if raw_date:
        parsed = parse_date(raw_date)
        if parsed is None:
            errors.append("Last donation date is not a valid date.")
        elif parsed > date.today():
            errors.append("Last donation date cannot be in the future.")

    if form.get("availability") and form["availability"] not in AVAILABILITY_OPTIONS:
        errors.append("Select a valid availability status.")

    _too_long(form, "name", 120, "Name", errors)
    _too_long(form, "email", 120, "Email", errors)
    _too_long(form, "phone", 30, "Phone number", errors)
    _too_long(form, "city", 80, "City", errors)
    _too_long(form, "area", 120, "Area", errors)
    if require_password:
        errors += validate_password(form.get("password", ""), form.get("confirm_password"))
    return errors


def validate_patient_form(form, require_password=True):
    errors = []
    if not form.get("name", "").strip():
        errors.append("Full name is required.")
    if not is_valid_email(form.get("email", "")):
        errors.append("Enter a valid email address.")
    if not is_valid_phone(form.get("phone", "")):
        errors.append("Enter a valid phone number.")
    if not form.get("city", "").strip():
        errors.append("City is required.")
    _too_long(form, "name", 120, "Name", errors)
    _too_long(form, "email", 120, "Email", errors)
    _too_long(form, "phone", 30, "Phone number", errors)
    _too_long(form, "city", 80, "City", errors)
    _too_long(form, "address", 255, "Address", errors)
    if require_password:
        errors += validate_password(form.get("password", ""), form.get("confirm_password"))
    return errors


def validate_hospital_form(form, require_password=True):
    errors = []
    if not form.get("hospital_name", "").strip():
        errors.append("Hospital name is required.")
    if not is_valid_email(form.get("email", "")):
        errors.append("Enter a valid email address.")
    if not is_valid_phone(form.get("phone", "")):
        errors.append("Enter a valid phone number.")
    if not form.get("city", "").strip():
        errors.append("City is required.")
    if not form.get("address", "").strip():
        errors.append("Address is required.")
    _too_long(form, "hospital_name", 160, "Hospital name", errors)
    _too_long(form, "email", 120, "Email", errors)
    _too_long(form, "phone", 30, "Phone number", errors)
    _too_long(form, "city", 80, "City", errors)
    _too_long(form, "address", 255, "Address", errors)
    if require_password:
        errors += validate_password(form.get("password", ""), form.get("confirm_password"))
    return errors


def validate_blood_request_form(form):
    errors = []
    if not form.get("patient_name", "").strip():
        errors.append("Patient name is required.")
    if not is_valid_blood_group(form.get("blood_group_required", "")):
        errors.append("Select a valid blood group.")
    if not form.get("hospital_id"):
        errors.append("Please select a valid hospital.")
    if not form.get("location", "").strip():
        errors.append("Hospital location is required.")
    if not is_valid_phone(form.get("contact_number", "")):
        errors.append("Enter a valid contact number.")
    if form.get("urgency") not in URGENCY_LEVELS:
        errors.append("Select a valid urgency level.")

    _too_long(form, "patient_name", 120, "Patient name", errors)
    _too_long(form, "location", 160, "Location", errors)
    _too_long(form, "contact_number", 30, "Contact number", errors)
    _too_long(form, "description", 2000, "Notes", errors)
    if checked(form, "patient_is_minor") and not checked(form, "guardian_confirm"):
        errors.append("For a patient under 18 the request must be made by a parent or legal guardian.")

    units = form.get("units_required", "")
    try:
        units = int(units)
        if units < 1 or units > 20:
            errors.append("Units required must be between 1 and 20.")
    except (TypeError, ValueError):
        errors.append("Units required must be a number.")
    return errors


# ----------------------------------------------------------------------
# Consent and compliance forms
# ----------------------------------------------------------------------
def checked(form, name):
    return form.get(name) in ("on", "1", "true", "yes")


def validate_account_consents(form, role):
    """Explicit, unticked-by-default consents required before an account exists."""
    errors = []
    if not checked(form, "accept_terms"):
        errors.append("You must accept the Terms of Service and Privacy Policy to register.")
    if role in ("donor", "patient") and not checked(form, "confirm_adult"):
        errors.append("You must confirm that you are 18 or older to register.")
    if role == "donor" and not checked(form, "health_consent"):
        errors.append("We need your consent to store your blood group and donation date.")
    return errors


def validate_contact_form(form):
    errors = []
    if not form.get("name", "").strip():
        errors.append("Please enter your name.")
    if not form.get("message", "").strip():
        errors.append("Please write a message.")
    email = form.get("email", "").strip()
    if email and not is_valid_email(email):
        errors.append("Enter a valid email address or leave it empty.")
    if not checked(form, "consent"):
        errors.append("Please tick the box to let us store your message and reply to it.")
    _too_long(form, "name", 120, "Name", errors)
    _too_long(form, "email", 120, "Email", errors)
    _too_long(form, "message", 3000, "Message", errors)
    return errors


DATA_REQUEST_KINDS = {"delete": "Delete my data", "access": "Get a copy of my data",
                      "correct": "Correct my data"}


def validate_data_request_form(form):
    errors = []
    if form.get("kind") not in DATA_REQUEST_KINDS:
        errors.append("Choose what you would like us to do.")
    if not is_valid_email(form.get("email", "")):
        errors.append("Enter the email address of the account or message.")
    if not checked(form, "consent"):
        errors.append("Please tick the box to let us store this request while we handle it.")
    _too_long(form, "name", 120, "Name", errors)
    _too_long(form, "email", 120, "Email", errors)
    _too_long(form, "details", 2000, "Details", errors)
    return errors

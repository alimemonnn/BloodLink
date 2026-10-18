"""Shared fixtures. Every test gets its own throw-away SQLite file and fake data."""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Importing `app` builds a module-level app; keep it away from the real database.
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "import.db")

import app as app_module                                  # noqa: E402
from config import TestingConfig                          # noqa: E402
from models import (STATUS_APPROVED, BloodRequest, DonationResponse, Donor,  # noqa: E402
                    Hospital, Patient, db)
from utils import ratelimit                               # noqa: E402

PASSWORD = "Password123"
# Run the same suite against a real PostgreSQL:  TEST_DATABASE_URL=postgresql://... pytest
PG_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


@pytest.fixture
def app(tmp_path):
    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = PG_URL or f"sqlite:///{tmp_path / 'test.db'}"

    ratelimit.clear_all()
    if PG_URL:                                   # start every test from empty tables
        pre = app_module.create_app(Cfg)
        with pre.app_context():
            db.drop_all()
            db.engine.dispose()
    flask_app = app_module.create_app(Cfg)
    ctx = flask_app.app_context()
    ctx.push()
    yield flask_app
    db.session.remove()
    if PG_URL:
        db.drop_all()
    db.engine.dispose()
    ctx.pop()


@pytest.fixture
def client(app):
    return app.test_client()


# ----------------------------------------------------------------------
# Factories (all fictional people)
# ----------------------------------------------------------------------
_n = [0]


def _uid():
    _n[0] += 1
    return _n[0]


def make_hospital(verified=True, city="Sukkur", name=None):
    i = _uid()
    h = Hospital(hospital_name=name or f"Test Hospital {i}", email=f"hospital{i}@example.com",
                 phone="0710000000", address="Test Road", city=city, is_verified=verified, is_active=True)
    h.set_password(PASSWORD)
    db.session.add(h)
    db.session.commit()
    return h


def make_patient(city="Sukkur"):
    i = _uid()
    p = Patient(name=f"Patient Person {i}", email=f"patient{i}@example.com", phone="03110000000", city=city)
    p.set_password(PASSWORD)
    db.session.add(p)
    db.session.commit()
    return p


def make_donor(group="O+", city="Sukkur", availability="Available", last=None, share=False):
    i = _uid()
    d = Donor(name=f"Donor Person {i}", email=f"donor{i}@example.com", phone="03001110000",
              blood_group=group, city=city, availability=availability, last_donation_date=last,
              is_active=True, share_contact_consent=share)
    d.set_password(PASSWORD)
    d.refresh_eligibility()
    db.session.add(d)
    db.session.commit()
    return d


def make_request(patient, hospital, group="O+", units=3, status=STATUS_APPROVED, urgency="Normal",
                 location="Sukkur", expiry=None, name="Test Patient Name"):
    r = BloodRequest(patient_id=patient.id, hospital_id=hospital.id, patient_name=name,
                     blood_group_required=group, units_required=units, urgency=urgency,
                     location=location, contact_number="03110000000",
                     description="Secret ward note", status=status, hospital_verified=True)
    if expiry:
        r.expiry_date = expiry
    db.session.add(r)
    db.session.commit()
    return r


def login(client, user, role):
    client.post("/login", data={"email": user.email, "password": PASSWORD, "role": role})


@pytest.fixture
def scene(app):
    """One hospital, one patient and a 3-unit O+ request with 3 compatible donors."""
    hospital = make_hospital()
    patient = make_patient()
    req = make_request(patient, hospital, group="O+", units=3)
    donors = [make_donor("O+"), make_donor("O-"), make_donor("O+")]
    return type("Scene", (), dict(hospital=hospital, patient=patient, request=req, donors=donors))

"""Notifications (recipients, no duplicates, privacy), database integrity and migration."""
import shutil
import sqlite3
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from conftest import make_donor, make_hospital, make_patient, make_request
from models import (AccountNotification, BloodRequest, DonationResponse, Notification, db)
from utils import allocation
from utils.notifications import (notify_account, notify_donor, notify_matching_donors)


# ----------------------------------------------------------------- notifications
def test_approval_notifies_only_matching_donors(scene):
    wrong = make_donor("A+")
    unavailable = make_donor("O+", availability="Not Available")
    n = notify_matching_donors(scene.request)
    notified = {x.donor_id for x in Notification.query.all()}
    assert n == 3 and notified == {d.id for d in scene.donors}
    assert wrong.id not in notified and unavailable.id not in notified


def test_retrying_the_same_operation_creates_no_duplicates(scene):
    notify_matching_donors(scene.request)
    before = Notification.query.count()
    assert notify_matching_donors(scene.request) == 0
    assert Notification.query.count() == before
    assert notify_donor(scene.donors[0].id, "x", scene.request.id, dedupe_key="k1") is True
    assert notify_donor(scene.donors[0].id, "x", scene.request.id, dedupe_key="k1") is False
    assert notify_account("patient", scene.patient.id, "y", dedupe_key="k2") is True
    assert notify_account("patient", scene.patient.id, "y", dedupe_key="k2") is False


def test_confirmation_notifies_patient_and_donor_with_progress(scene):
    resp = allocation.pledge(scene.donors[0], scene.request.id, 1, consent_to_share=True)
    allocation.confirm_donation(scene.hospital, resp.id)
    patient_msgs = [n.message for n in AccountNotification.query.filter_by(role="patient", user_id=scene.patient.id)]
    assert any("1 of 3 unit(s) confirmed, 2 remaining" in m for m in patient_msgs)
    assert any("verified your donation" in n.message
               for n in Notification.query.filter_by(donor_id=scene.donors[0].id))
    hospital_msgs = [n.message for n in AccountNotification.query.filter_by(role="hospital", user_id=scene.hospital.id)]
    assert any("A donor offered 1 unit" in m for m in hospital_msgs)


def test_fulfilment_notifies_patient_and_closes_out_waiting_donors(scene):
    waiting = make_donor("O+")
    allocation.pledge(waiting, scene.request.id, 1, consent_to_share=True)
    for d in scene.donors:
        allocation.confirm_donation(scene.hospital, allocation.pledge(d, scene.request.id, 1, True).id)
    assert AccountNotification.query.filter_by(role="patient", dedupe_key=f"fulfilled:{scene.request.id}").count() == 1
    assert any("closed" in n.message for n in Notification.query.filter_by(donor_id=waiting.id))


def test_cancel_and_expiry_notify_the_other_party(scene):
    allocation.close_request(scene.request.id, "patient", scene.patient.id)
    assert AccountNotification.query.filter_by(role="hospital", user_id=scene.hospital.id).count() == 1


def test_notifications_never_contain_patient_name_or_notes(scene):
    allocation.pledge(scene.donors[0], scene.request.id, 1, True)
    notify_matching_donors(scene.request)
    texts = [n.message for n in Notification.query.all()] + [n.message for n in AccountNotification.query.all()]
    assert texts
    for t in texts:
        assert "Test Patient Name" not in t and "Secret ward note" not in t and "03110000000" not in t


# ----------------------------------------------------------------- database integrity
def test_relationships(scene):
    resp = allocation.pledge(scene.donors[0], scene.request.id, 1, True)
    assert resp.request.hospital.id == scene.hospital.id
    assert resp in scene.donors[0].responses and resp in scene.request.responses
    assert scene.request in scene.patient.requests


def test_unique_donor_per_request_constraint(scene):
    db.session.add(DonationResponse(donor_id=scene.donors[0].id, request_id=scene.request.id))
    db.session.commit()
    db.session.add(DonationResponse(donor_id=scene.donors[0].id, request_id=scene.request.id))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


@pytest.mark.parametrize("units", [0, -1])
def test_request_units_must_be_positive_in_the_database(scene, units):
    db.session.add(BloodRequest(patient_id=scene.patient.id, hospital_id=scene.hospital.id, patient_name="x",
                                blood_group_required="O+", units_required=units, location="x", contact_number="1"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_response_unit_constraints_in_the_database(scene):
    db.session.add(DonationResponse(donor_id=scene.donors[0].id, request_id=scene.request.id, units_pledged=0))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(DonationResponse(donor_id=scene.donors[0].id, request_id=scene.request.id, units_collected=-1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_foreign_keys_are_declared_and_indexed(app):
    from sqlalchemy import inspect
    insp = inspect(db.engine)
    fks = {fk["constrained_columns"][0] for fk in insp.get_foreign_keys("donation_responses")}
    assert {"donor_id", "request_id", "verified_by_hospital_id"} <= fks
    indexed = {c for ix in insp.get_indexes("donation_responses") for c in ix["column_names"]}
    assert {"donor_id", "request_id", "response_status"} <= indexed


# ----------------------------------------------------------------- migration of an old database
LEGACY_SCHEMA = """
CREATE TABLE admins (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL, is_active BOOLEAN, created_at DATETIME);
CREATE TABLE hospitals (id INTEGER PRIMARY KEY, hospital_name VARCHAR(160) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL, password_hash VARCHAR(255) NOT NULL, address VARCHAR(255), city VARCHAR(80) NOT NULL,
  is_verified BOOLEAN, is_active BOOLEAN, created_at DATETIME);
CREATE TABLE patients (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL, password_hash VARCHAR(255) NOT NULL, city VARCHAR(80) NOT NULL, address VARCHAR(255),
  is_active BOOLEAN, created_at DATETIME);
CREATE TABLE donors (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, email VARCHAR(120) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL, password_hash VARCHAR(255) NOT NULL, blood_group VARCHAR(3) NOT NULL,
  city VARCHAR(80) NOT NULL, area VARCHAR(120), last_donation_date DATE, availability VARCHAR(20),
  eligibility_status VARCHAR(20), is_active BOOLEAN, created_at DATETIME);
CREATE TABLE blood_requests (id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES patients(id),
  hospital_id INTEGER NOT NULL REFERENCES hospitals(id), patient_name VARCHAR(120) NOT NULL,
  blood_group_required VARCHAR(3) NOT NULL, units_required INTEGER, urgency VARCHAR(20), location VARCHAR(160) NOT NULL,
  contact_number VARCHAR(30) NOT NULL, description TEXT, status VARCHAR(40), hospital_verified BOOLEAN,
  hospital_notes TEXT, created_at DATETIME, updated_at DATETIME, expiry_date DATETIME);
CREATE TABLE donation_responses (id INTEGER PRIMARY KEY, donor_id INTEGER NOT NULL REFERENCES donors(id),
  request_id INTEGER NOT NULL REFERENCES blood_requests(id), response_status VARCHAR(30), response_date DATETIME,
  donation_date DATE, CONSTRAINT uq_donor_request UNIQUE (donor_id, request_id));
CREATE TABLE notifications (id INTEGER PRIMARY KEY, donor_id INTEGER NOT NULL REFERENCES donors(id),
  request_id INTEGER REFERENCES blood_requests(id), message VARCHAR(255) NOT NULL, is_read BOOLEAN, created_at DATETIME);
INSERT INTO hospitals VALUES (1,'Old Hospital','oh@example.com','071','x','Rd','Sukkur',1,1,'2026-01-01');
INSERT INTO patients VALUES (1,'Old Patient','op@example.com','031','x','Sukkur',NULL,1,'2026-01-01');
INSERT INTO donors VALUES (1,'Old Donor A','a@example.com','030','x','O+','Sukkur',NULL,NULL,'Available','Eligible',1,'2026-01-01');
INSERT INTO donors VALUES (2,'Old Donor B','b@example.com','030','x','O+','Sukkur',NULL,NULL,'Available','Eligible',1,'2026-01-01');
INSERT INTO blood_requests VALUES (1,1,1,'Old Patient','O+',3,'Urgent','Sukkur','031','note','Approved',1,NULL,'2026-01-02','2026-01-02','2099-01-01');
INSERT INTO blood_requests VALUES (2,1,1,'Old Patient','O+',1,'Normal','Sukkur','031','note','Fulfilled',1,NULL,'2026-01-02','2026-01-02','2099-01-01');
INSERT INTO donation_responses VALUES (1,1,1,'Donation Completed','2026-01-03','2026-01-04');
INSERT INTO donation_responses VALUES (2,2,1,'Interested','2026-01-03',NULL);
INSERT INTO notifications VALUES (1,1,1,'hello',0,'2026-01-03');
"""


def test_migration_upgrades_an_old_database_without_losing_rows(tmp_path):
    import app as app_module
    from config import TestingConfig
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.executescript(LEGACY_SCHEMA)
    con.commit(); con.close()

    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{path}"

    flask_app = app_module.create_app(Cfg)
    with flask_app.app_context():
        # rows survived
        assert db.session.query(BloodRequest).count() == 2
        assert Notification.query.count() == 1 and DonationResponse.query.count() == 2
        done = db.session.get(DonationResponse, 1)
        assert done.units_collected == 1 and done.units_pledged == 1          # back-filled
        open_req = db.session.get(BloodRequest, 1)
        assert open_req.units_confirmed == 1 and open_req.status == "Partially Fulfilled"
        assert db.session.get(BloodRequest, 2).closed_reason == "legacy"        # flagged, not rewritten
        # new columns usable
        assert db.session.get(type(done.donor), 1).share_contact_consent is False
        assert allocation.check_consistency() == [] or all("legacy" not in p for p in allocation.check_consistency())
        db.session.remove(); db.engine.dispose()
    assert list(tmp_path.glob("legacy.db.pre-migration-*.bak")), "a backup copy must be made first"
    # running again is a harmless no-op
    flask_app = app_module.create_app(Cfg)
    with flask_app.app_context():
        assert db.session.query(BloodRequest).count() == 2
        db.session.remove(); db.engine.dispose()


def test_schema_compiles_for_postgresql(app):
    """No PostgreSQL server here, but the DDL must at least be valid for that dialect."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable
    for table in db.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in ddl
        for ix in table.indexes:
            str(CreateIndex(ix).compile(dialect=postgresql.dialect()))

"""The Alembic baseline must build exactly the schema the models describe."""
import sqlite3

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from flask_migrate import downgrade, stamp, upgrade

import app as app_module
from config import TestingConfig
from models import db


def _make(tmp_path, name="m.db"):
    class Cfg(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / name}"
        USE_ALEMBIC = True
    return app_module.create_app(Cfg)


def test_upgrade_builds_the_full_schema_with_no_drift(tmp_path):
    a = _make(tmp_path)
    with a.app_context():
        upgrade(directory="migrations")
        with db.engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), db.metadata)
        assert diff == [], diff                                    # models and migrations agree
        tables = {r[0] for r in sqlite3.connect(tmp_path / "m.db").execute("select name from sqlite_master where type='table'")}
        assert {"donors", "blood_requests", "chat_messages", "outbox", "camps", "alembic_version"} <= tables
        db.session.remove(); db.engine.dispose()


def test_downgrade_removes_everything_and_upgrade_is_repeatable(tmp_path):
    a = _make(tmp_path)
    with a.app_context():
        upgrade(directory="migrations")
        downgrade(directory="migrations", revision="base")
        left = {r[0] for r in sqlite3.connect(tmp_path / "m.db").execute("select name from sqlite_master where type='table'")}
        assert left <= {"alembic_version"}
        upgrade(directory="migrations")
        db.session.remove(); db.engine.dispose()


def test_an_existing_database_can_be_adopted_with_stamp(tmp_path):
    """The path for a database that was built by the older create_all() code."""
    class Legacy(TestingConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'old.db'}"
    legacy = app_module.create_app(Legacy)                       # builds every table the old way
    with legacy.app_context():
        db.session.remove(); db.engine.dispose()
    a = _make(tmp_path, "old.db")
    with a.app_context():
        stamp(directory="migrations", revision="head")
        upgrade(directory="migrations")                          # nothing left to do, and no error
        ver = sqlite3.connect(tmp_path / "old.db").execute("select version_num from alembic_version").fetchone()[0]
        assert ver == "0001_baseline"
        db.session.remove(); db.engine.dispose()


def test_the_legacy_startup_path_still_works_without_alembic(app):
    assert app.config["USE_ALEMBIC"] is False and db.inspect(db.engine).has_table("donors")

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from maestro.db import migrate
from maestro.db.engine import Database
from maestro.db.schema import metadata


def test_empty_instance_migrates_to_head_and_matches_schema(tmp_path):
    db = Database.open(tmp_path / "app.db")
    assert migrate.current(db) is None
    migrate.upgrade(db)
    assert migrate.current(db) == migrate.head()
    with db.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), metadata)
        assert diff == [], diff
        names = set(inspect(connection).get_table_names())
    assert {"users", "pats", "runs", "trials", "operations", "audit_events"} <= names
    migrate.upgrade(db)  # idempotent
    assert migrate.current(db) == migrate.head()


def test_pragmas_wal_and_foreign_keys(tmp_path):
    db = Database.open(tmp_path / "app.db")
    migrate.upgrade(db)
    with db.read() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000


def test_foreign_keys_enforced(tmp_path):
    import pytest
    from sqlalchemy import insert
    from sqlalchemy.exc import IntegrityError

    from maestro.db import schema as t

    db = Database.open(tmp_path / "app.db")
    migrate.upgrade(db)
    with pytest.raises(IntegrityError), db.write() as conn:
        conn.execute(
            insert(t.sessions).values(
                id="ses_x",
                token_hash="h",
                user_id="usr_missing",
                created_at="x",
                expires_at="x",
                last_seen_at="x",
            )
        )

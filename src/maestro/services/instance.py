"""Stable instance identity: scopes Docker labels so cleanup never touches another instance."""

from sqlalchemy import insert, select

from maestro.core import clock
from maestro.core.ids import new_id
from maestro.db import schema as t
from maestro.db.engine import Database


def instance_id(db: Database) -> str:
    with db.write() as conn:
        found = conn.execute(select(t.instance.c.instance_id)).scalar()
        if found:
            return found
        value = new_id("inst")
        conn.execute(
            insert(t.instance).values(
                singleton=1, instance_id=value, created_at=clock.to_text(clock.now())
            )
        )
        return value

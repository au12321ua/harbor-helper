"""Objects persistence operations sharing the service store."""

import json

from harbor_helper.service.primitives import (
    ServiceError,
    public_object,
)


class Objects:
    def objects(self, kind):
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT o.* FROM objects o JOIN
                (SELECT id,MAX(version) v FROM objects WHERE kind=? GROUP BY id) c
                ON c.id=o.id AND c.v=o.version WHERE o.kind=? ORDER BY o.id""",
                (kind, kind),
            ).fetchall()
        return [public_object(r) for r in rows]

    def object(self, kind, object_id, version=None):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM objects WHERE kind=? AND id=? "
                + ("AND version=?" if version else "ORDER BY version DESC LIMIT 1"),
                (kind, object_id, version) if version else (kind, object_id),
            ).fetchone()
        if row is None:
            raise ServiceError("unknown_configuration", "Configuration not found", 404)
        return public_object(row)

    def save_version(self, kind, value):
        object_id = value["id"]
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            version = db.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM objects WHERE kind=? AND id=?",
                (kind, object_id),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO objects VALUES(?,?,?,?)", (kind, object_id, version, json.dumps(value))
            )
        return {**value, "version": version}

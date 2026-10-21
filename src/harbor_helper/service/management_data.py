"""Additive management metadata. Original frozen records are never rewritten."""

import json
import time
import unicodedata
import uuid

from harbor_helper.service.primitives import ServiceError


def name_key(name):
    return unicodedata.normalize("NFKC", name.strip()).casefold()


def reserve_name(db, kind, object_id, name, *, converting=False):
    """Atomic team names, including recycled objects; empty group names are exempt."""
    key = name_key(name)
    suffix = 0
    original = name
    while key:
        old = db.execute(
            "SELECT id FROM management_names WHERE kind=? AND normalized=?", (kind, key)
        ).fetchone()
        if not old or old["id"] == object_id:
            break
        if not converting:
            raise ServiceError(
                "name_conflict", "名称已被使用（包括回收站）；请恢复原对象或改名", 409
            )
        suffix += 1
        name = original[:85] + f"（升级前·{object_id[:12]}·{suffix}）"
        key = name_key(name)
    db.execute("DELETE FROM management_names WHERE kind=? AND id=?", (kind, object_id))
    if key:
        db.execute("INSERT INTO management_names VALUES(?,?,?,?)", (kind, object_id, key, name))
    return name


def allocate(db, kind, object_id):
    db.execute(
        "INSERT INTO management_counters VALUES(?,?,0) ON CONFLICT DO NOTHING", (kind, object_id)
    )
    db.execute(
        "UPDATE management_counters SET high=high+1 WHERE kind=? AND id=?", (kind, object_id)
    )
    return db.execute(
        "SELECT high FROM management_counters WHERE kind=? AND id=?", (kind, object_id)
    ).fetchone()[0]


def link_request(
    db, request_id, owner, name, source=None, relation="independent", *, converting=False
):
    old = db.execute("SELECT * FROM request_links WHERE id=?", (request_id,)).fetchone()
    if old:
        return dict(old)
    parent = (
        db.execute("SELECT * FROM request_links WHERE id=?", (source,)).fetchone()
        if source
        else None
    )
    if source and not parent:
        raise ServiceError("source_request_missing", "来源请求不可用", 409)
    if parent and relation != "copy":
        group_id = parent["group_id"]
    else:
        group_id = "grp-" + (
            uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex if converting else uuid.uuid4().hex
        )
        name = reserve_name(db, "group", group_id, name, converting=converting)
        db.execute(
            "INSERT INTO request_groups VALUES(?,?,?,?,?)",
            (group_id, name, owner, time.time(), int(converting)),
        )
    number = allocate(db, "group", group_id)
    db.execute(
        "INSERT INTO request_links VALUES(?,?,?,?,?)",
        (request_id, group_id, number, source, relation),
    )
    return dict(db.execute("SELECT * FROM request_links WHERE id=?", (request_id,)).fetchone())


def initialize(store):
    with store.connect() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS management_names (
                kind TEXT NOT NULL, id TEXT NOT NULL, normalized TEXT NOT NULL, display TEXT NOT NULL,
                PRIMARY KEY(kind,id), UNIQUE(kind,normalized));
            CREATE TABLE IF NOT EXISTS management_counters (
                kind TEXT NOT NULL, id TEXT NOT NULL, high INTEGER NOT NULL, PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS request_groups (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, creator_id TEXT NOT NULL, created REAL NOT NULL,
                auto_named INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS request_links (
                id TEXT PRIMARY KEY, group_id TEXT NOT NULL, number INTEGER NOT NULL,
                source_id TEXT, relation TEXT NOT NULL, UNIQUE(group_id,number));
            CREATE TABLE IF NOT EXISTS dataset_identities (
                id TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT NOT NULL,
                default_version TEXT, auto_named INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS dataset_sources (
                id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, number INTEGER NOT NULL,
                resolved TEXT NOT NULL, config TEXT NOT NULL, created REAL NOT NULL,
                UNIQUE(dataset_id,resolved), UNIQUE(dataset_id,number));
            CREATE TABLE IF NOT EXISTS dataset_previews (
                id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL, source_version INTEGER,
                config TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS dataset_aliases (id TEXT PRIMARY KEY, target TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recycle_events (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, object_id TEXT NOT NULL,
                owner_id TEXT NOT NULL, actor_id TEXT NOT NULL, created REAL NOT NULL,
                state TEXT NOT NULL, members TEXT NOT NULL, cleanup TEXT,
                restored REAL, purged REAL);
            CREATE TABLE IF NOT EXISTS purge_receipts (
                user_id TEXT NOT NULL, key_hash TEXT NOT NULL, event_id TEXT NOT NULL,
                PRIMARY KEY(user_id,key_hash));
            CREATE TABLE IF NOT EXISTS recycled_objects (
                kind TEXT NOT NULL, id TEXT NOT NULL, event_id TEXT NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY(kind,id));
        """)
        db.execute("CREATE TABLE IF NOT EXISTS management_schema (version INTEGER PRIMARY KEY)")
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM management_schema WHERE version=1").fetchone():
            return
        # Every original revision remains in objects, including drafts and conflicting parameters.
        datasets = db.execute(
            "SELECT * FROM objects WHERE kind='dataset' ORDER BY id,version"
        ).fetchall()
        for row in datasets:
            value = json.loads(row["config"])
            identity = db.execute(
                "SELECT * FROM dataset_identities WHERE id=?", (row["id"],)
            ).fetchone()
            if not identity:
                original = value.get("name") or row["id"]
                name = reserve_name(db, "dataset", row["id"], original, converting=True)
                source = value.get("reference", "").split("@")[0]
                db.execute(
                    "INSERT INTO dataset_identities VALUES(?,?,?,?,?)",
                    (row["id"], source, name, None, int(name != original)),
                )
            remember_dataset(db, row["id"], value)
        for row in db.execute("SELECT * FROM attachments ORDER BY created,id").fetchall():
            if not db.execute(
                "SELECT 1 FROM management_names WHERE kind='attachment' AND id=?", (row["id"],)
            ).fetchone():
                name = reserve_name(db, "attachment", row["id"], row["name"], converting=True)
                db.execute("UPDATE attachments SET name=? WHERE id=?", (name, row["id"]))
            high = db.execute(
                "SELECT COALESCE(MAX(number),0) FROM attachment_versions WHERE attachment_id=?",
                (row["id"],),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO management_counters VALUES('attachment',?,?) ON CONFLICT(kind,id) DO UPDATE SET high=MAX(high,excluded.high)",
                (row["id"], high),
            )
        for dataset_id in {r["id"] for r in datasets}:
            latest = next(r for r in reversed(datasets) if r["id"] == dataset_id)
            value = json.loads(latest["config"])
            selected = (
                db.execute(
                    "SELECT id FROM dataset_sources WHERE dataset_id=? AND resolved=?",
                    (dataset_id, value.get("resolved")),
                ).fetchone()
                if value.get("status") == "verified"
                else None
            )
            db.execute(
                "UPDATE dataset_identities SET default_version=? WHERE id=?",
                (selected[0] if selected else None, dataset_id),
            )
        submissions = db.execute("SELECT * FROM submissions ORDER BY created,id").fetchall()
        by_run = {r["run_id"]: r["id"] for r in submissions if r["run_id"]}
        pending = list(submissions)
        while pending:
            remaining = []
            for row in pending:
                frozen = json.loads(row["frozen"])
                binding = frozen.get("service", {})
                source = binding.get("recovered_submission") or by_run.get(row["parent"])
                if (
                    source
                    and not db.execute(
                        "SELECT 1 FROM request_links WHERE id=?", (source,)
                    ).fetchone()
                ):
                    remaining.append(row)
                    continue
                link_request(
                    db,
                    row["id"],
                    row["user_id"],
                    binding.get("name", ""),
                    source,
                    row["operation"] if source else "unknown",
                    converting=True,
                )
            if len(remaining) == len(pending):
                # Damaged cycles/missing sources are unknown, never guessed by display names.
                for row in remaining:
                    binding = json.loads(row["frozen"]).get("service", {})
                    link_request(
                        db, row["id"], row["user_id"], binding.get("name", ""), converting=True
                    )
                break
            pending = remaining
        for row in db.execute(
            "SELECT * FROM operations WHERE operation IN ('submit','rerun','retry','recover') ORDER BY created,id"
        ).fetchall():
            if row["status"] == "rejected":
                body = json.loads(row["request"])
                link_request(
                    db,
                    row["id"],
                    row["user_id"],
                    body.get("name", body.get("body", {}).get("name", "")) or "",
                    converting=True,
                )

        db.execute("INSERT INTO management_schema VALUES(1)")


def remember_dataset(db, dataset_id, value):
    resolved = value.get("resolved")
    if value.get("status") != "verified" or not resolved or "@sha256:" not in resolved:
        return None
    row = db.execute(
        "SELECT id FROM dataset_sources WHERE dataset_id=? AND resolved=?", (dataset_id, resolved)
    ).fetchone()
    if row:
        version_id = row["id"]
    else:
        version_id = "dv-" + uuid.uuid4().hex
        number = allocate(db, "dataset", dataset_id)
        db.execute(
            "INSERT INTO dataset_sources VALUES(?,?,?,?,?,?)",
            (version_id, dataset_id, number, resolved, json.dumps(value), time.time()),
        )
    db.execute(
        "UPDATE dataset_identities SET default_version=COALESCE(default_version,?) WHERE id=?",
        (version_id, dataset_id),
    )
    return version_id


def state(db, kind, object_id):
    row = db.execute(
        "SELECT state FROM recycled_objects WHERE kind=? AND id=?", (kind, object_id)
    ).fetchone()
    return row["state"] if row else "active"


def available(db, kind, object_id):
    current = state(db, kind, object_id)
    if current != "active":
        raise ServiceError(
            "object_" + current,
            "对象在回收站，请先恢复" if current == "recycled" else "对象已永久删除",
            409 if current == "recycled" else 410,
        )


def request_id(db, object_id):
    row = db.execute("SELECT id FROM submissions WHERE run_id=?", (object_id,)).fetchone()
    return row["id"] if row else object_id

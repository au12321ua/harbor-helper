"""Explicit recycle events and retryable cleanup over concrete service dependencies."""

import hashlib
import json
import shutil
import time
import uuid

from harbor_helper.persistence.statuses import TERMINAL
from harbor_helper.service.management_data import available, request_id
from harbor_helper.service.permissions import management_admin
from harbor_helper.service.primitives import ServiceError

KINDS = {"request", "dataset", "dataset_version", "attachment", "attachment_version", "artifact"}


class Recycle:
    def __init__(self, app):
        import weakref

        self.app, self.data, self.store = weakref.proxy(app), app.data, app.store

    def allowed(self, actor, owner, kind, *, purge=False):
        token = bool(actor.get("access_credential_id"))
        role = actor.get("account_role", actor["role"])
        scopes = set(actor.get("scopes", []))
        own = owner == actor["id"] and kind in {"request", "attachment", "attachment_version"}
        all_items = role == "admin" and (not token or "recycle_all" in scopes)
        if not all_items and not (own and (not token or "recycle_own" in scopes)):
            raise ServiceError("recycle_forbidden", "无权管理该回收项", 403)
        if purge:
            management_admin(actor, "purge")

    def members(self, db, kind, object_id):
        if kind == "request":
            object_id = request_id(db, object_id)
            row = db.execute("SELECT * FROM submissions WHERE id=?", (object_id,)).fetchone()
            if row:
                if row["status"] not in {"ready", "failed", "cancelled"}:
                    raise ServiceError("resource_active", "先取消任务并等待执行资源释放", 409)
                if row["run_id"]:
                    run = self.store.get(row["run_id"])
                    if run["status"] not in TERMINAL:
                        raise ServiceError("resource_active", "执行资源尚未确认释放", 409)
                return object_id, row["user_id"], [("request", object_id)]
            row = db.execute(
                "SELECT * FROM operations WHERE id=? AND operation IN ('submit','rerun','retry','recover')",
                (object_id,),
            ).fetchone()
            if row:
                return object_id, row["user_id"], [("request", object_id)]
        elif kind in {"attachment", "attachment_version"}:
            row = db.execute(
                "SELECT * FROM "
                + ("attachments" if kind == "attachment" else "attachment_versions")
                + " WHERE id=?",
                (object_id,),
            ).fetchone()
            if row:
                identity = (
                    row
                    if kind == "attachment"
                    else db.execute(
                        "SELECT * FROM attachments WHERE id=?", (row["attachment_id"],)
                    ).fetchone()
                )
                available(db, "attachment", identity["id"])
                members = [(kind, object_id)]
                if kind == "attachment":
                    members += [
                        ("attachment_version", r[0])
                        for r in db.execute(
                            "SELECT id FROM attachment_versions WHERE attachment_id=? ORDER BY number",
                            (object_id,),
                        )
                    ]
                return object_id, identity["creator_id"], members
        elif kind in {"dataset", "dataset_version"}:
            row = db.execute(
                "SELECT * FROM "
                + ("dataset_identities" if kind == "dataset" else "dataset_sources")
                + " WHERE id=?",
                (object_id,),
            ).fetchone()
            if row:
                identity = row["id"] if kind == "dataset" else row["dataset_id"]
                alias = db.execute(
                    "SELECT target FROM dataset_aliases WHERE id=?", (identity,)
                ).fetchone()
                available(db, "dataset", alias[0] if alias else identity)
                if alias and kind == "dataset":
                    raise ServiceError("dataset_alias", "请管理合并后的目标数据集", 409)
                members = [(kind, object_id)]
                if kind == "dataset":
                    members += [
                        ("dataset_version", r[0])
                        for r in db.execute(
                            "SELECT id FROM dataset_sources WHERE dataset_id=? OR dataset_id IN (SELECT id FROM dataset_aliases WHERE target=?) ORDER BY dataset_id,number",
                            (object_id, object_id),
                        )
                    ]
                return object_id, "", members
        elif kind == "artifact":
            parts = object_id.split(":", 1)
            if len(parts) == 2:
                run_id, file_id = parts
                available(db, "request", request_id(db, run_id))
                if self.store.get(run_id)["status"] not in TERMINAL:
                    raise ServiceError("resource_active", "产物回收须等待执行资源释放", 409)
                self.app.artifact_path(run_id, file_id)
                return object_id, "", [("artifact", object_id)]
        raise ServiceError("recycle_missing", "对象不存在", 404)

    def move(self, actor, kind, object_id, expected=None):
        if kind not in KINDS:
            raise ServiceError("recycle_kind", "未知回收对象")
        with self.store.control(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if kind == "request":
                object_id = request_id(db, object_id)
            current = db.execute(
                "SELECT * FROM recycled_objects WHERE kind=? AND id=?", (kind, object_id)
            ).fetchone()
            if current and current["state"] != "active":
                event = self._event(db, current["event_id"])
                self.allowed(actor, event["owner_id"], event["kind"])
                return self.public(event)
            object_id, owner, members = self.members(db, kind, object_id)
            self.allowed(actor, owner, kind)
            if kind in {"dataset", "attachment"} and expected != [m[1] for m in members[1:]]:
                raise ServiceError(
                    "recycle_changed", "请预览并确认当前全部版本（含已回收版本）", 409
                )
            event_id = "rec-" + uuid.uuid4().hex
            prior = []
            for child_kind, child_id in members:
                old = db.execute(
                    "SELECT * FROM recycled_objects WHERE kind=? AND id=?", (child_kind, child_id)
                ).fetchone()
                previous = dict(old) if old else None
                if old and old["state"] == "recycled":
                    db.execute(
                        "UPDATE recycle_events SET state='included' WHERE id=?", (old["event_id"],)
                    )
                prior.append({"kind": child_kind, "id": child_id, "previous": previous})
                db.execute(
                    "INSERT INTO recycled_objects VALUES(?,?,?,'recycled') ON CONFLICT(kind,id) DO UPDATE SET event_id=excluded.event_id,state='recycled'",
                    (child_kind, child_id, event_id),
                )
                if child_kind == "dataset":
                    db.execute(
                        "UPDATE configuration_settings SET config=json_set(config,'$.default_dataset_id',NULL) WHERE json_extract(config,'$.default_dataset_id')=?",
                        (child_id,),
                    )
                    db.execute(
                        "UPDATE dataset_identities SET default_version=NULL WHERE id=?", (child_id,)
                    )
                if child_kind == "dataset_version":
                    db.execute(
                        "UPDATE dataset_identities SET default_version=NULL WHERE default_version=?",
                        (child_id,),
                    )
            db.execute(
                "INSERT INTO recycle_events VALUES(?,?,?,?,?,?,'recycled',?,NULL,NULL,NULL)",
                (event_id, kind, object_id, owner, actor["id"], time.time(), json.dumps(prior)),
            )
            db.execute(
                "INSERT INTO access_events(user_id,access_credential_id,action,object_id,time) VALUES(?,?,?,?,?)",
                (actor["id"], actor.get("access_credential_id"), "recycle", event_id, time.time()),
            )
            event = self._event(db, event_id)
        return self.public(event)

    def _event(self, db, event_id):
        row = db.execute("SELECT * FROM recycle_events WHERE id=?", (event_id,)).fetchone()
        if not row:
            raise ServiceError("recycle_missing", "回收事件不存在", 404)
        return dict(row)

    def public(self, event):
        return {
            k: event[k]
            for k in (
                "id",
                "kind",
                "object_id",
                "owner_id",
                "actor_id",
                "created",
                "state",
                "cleanup",
            )
        } | {"count": len(json.loads(event["members"]))}

    def listing(self, actor):
        with self.store.connect() as db:
            values = []
            for row in db.execute("SELECT * FROM recycle_events ORDER BY created DESC").fetchall():
                try:
                    self.allowed(actor, row["owner_id"], row["kind"])
                except ServiceError:
                    continue
                values.append(self.public(dict(row)))
        return {"items": values}

    def restore(self, actor, event_id):
        with self.store.control(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            event = self._event(db, event_id)
            self.allowed(actor, event["owner_id"], event["kind"])
            if event["state"] == "restored":
                return self.public(event)
            if event["state"] != "recycled":
                raise ServiceError(
                    "recycle_event_state", "此事件已并入父项或进入永久删除，不能恢复", 409
                )
            if event["kind"] == "artifact":
                run_id, _file_id = event["object_id"].split(":", 1)
                try:
                    if (self.store.path(run_id) / "archived.json").exists():
                        raise ServiceError(
                            "artifact_expired", "既有保留期已清理产物，无法恢复", 410
                        )
                    self.app.artifact_cleanup_path(run_id, _file_id)
                except ServiceError:
                    db.execute(
                        "UPDATE recycle_events SET state='expired',cleanup='retention expired' WHERE id=?",
                        (event_id,),
                    )
                    db.execute(
                        "UPDATE recycled_objects SET state='purged' WHERE kind='artifact' AND id=? AND event_id=?",
                        (event["object_id"], event_id),
                    )
                    db.commit()
                    raise ServiceError(
                        "artifact_expired", "产物已被保留期清理或不可用，无法恢复", 410
                    ) from None
            for member in json.loads(event["members"]):
                old = member["previous"]
                if old and old["state"] == "recycled":
                    # Reactivate exactly the old child event; later events have distinct IDs.
                    db.execute(
                        "UPDATE recycled_objects SET event_id=?,state='recycled' WHERE kind=? AND id=? AND event_id=?",
                        (old["event_id"], member["kind"], member["id"], event_id),
                    )
                    db.execute(
                        "UPDATE recycle_events SET state='recycled' WHERE id=? AND state='included'",
                        (old["event_id"],),
                    )
                else:
                    db.execute(
                        "UPDATE recycled_objects SET state='active' WHERE kind=? AND id=? AND event_id=?",
                        (member["kind"], member["id"], event_id),
                    )
            db.execute(
                "UPDATE recycle_events SET state='restored',restored=? WHERE id=?",
                (time.time(), event_id),
            )
            event["state"] = "restored"
            db.execute(
                "INSERT INTO access_events(user_id,access_credential_id,action,object_id,time) VALUES(?,?,?,?,?)",
                (actor["id"], actor.get("access_credential_id"), "restore", event_id, time.time()),
            )
        return self.public(event)

    def purge(self, actor, event_id, idem):
        if (
            not isinstance(idem, str)
            or not 1 <= len(idem) <= 128
            or any(ord(c) < 33 or ord(c) > 126 for c in idem)
        ):
            raise ServiceError("idempotency_required", "永久删除需要独立的幂等键")
        with self.store.control(), self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            event = self._event(db, event_id)
            self.allowed(actor, event["owner_id"], event["kind"], purge=True)
            key_hash = hashlib.sha256(idem.encode()).hexdigest()
            receipt = db.execute(
                "SELECT event_id FROM purge_receipts WHERE user_id=? AND key_hash=?",
                (actor["id"], key_hash),
            ).fetchone()
            if receipt and receipt[0] != event_id:
                raise ServiceError("idempotency_conflict", "此永久删除幂等键已绑定其他事件", 409)
            if event["state"] == "purged":
                db.execute(
                    "INSERT OR IGNORE INTO purge_receipts VALUES(?,?,?)",
                    (actor["id"], key_hash, event_id),
                )
                return self.public(event)
            if event["state"] not in {"recycled", "purging"}:
                raise ServiceError(
                    "recycle_event_state",
                    "只能永久删除当前回收事件；旧事件不能删除后来回收的对象",
                    409,
                )
            db.execute(
                "INSERT OR IGNORE INTO purge_receipts VALUES(?,?,?)",
                (actor["id"], key_hash, event_id),
            )
            members = json.loads(event["members"])
            for m in members:
                db.execute(
                    "UPDATE recycled_objects SET state='purged' WHERE kind=? AND id=? AND event_id=?",
                    (m["kind"], m["id"], event_id),
                )
                self._scrub_operations(db, m["kind"], m["id"])
            db.execute(
                "UPDATE recycle_events SET state='purging',cleanup='pending' WHERE id=?",
                (event_id,),
            )
        # Persist removal of read access before touching files. A crash is retryable.
        with self.store.control():
            pending = []
            for m in sorted(members, key=lambda m: m["kind"] in {"attachment", "dataset"}):
                try:
                    reason = self._cleanup(m["kind"], m["id"])
                except (OSError, ValueError):
                    reason = "清理失败：文件或证据锁不可用，请重试"
                if reason:
                    pending.append(reason)
            with self.store.connect() as db:
                db.execute(
                    "UPDATE recycle_events SET state=?,cleanup=?,purged=? WHERE id=?",
                    (
                        "purging" if pending else "purged",
                        "; ".join(sorted(set(pending))) if pending else "complete",
                        None if pending else time.time(),
                        event_id,
                    ),
                )
                for m in members:
                    if m["previous"] and m["previous"]["state"] == "recycled":
                        db.execute(
                            "UPDATE recycle_events SET state='purged',cleanup=? WHERE id=?",
                            ("included in " + event_id, m["previous"]["event_id"]),
                        )
                db.execute(
                    "INSERT INTO access_events(user_id,access_credential_id,action,object_id,time) VALUES(?,?,?,?,?)",
                    (
                        actor["id"],
                        actor.get("access_credential_id"),
                        "purge",
                        event_id,
                        time.time(),
                    ),
                )
                return self.public(self._event(db, event_id))

    def _scrub_operations(self, db, kind, object_id):
        if kind == "request":
            operations = db.execute(
                "SELECT id FROM operations WHERE id=? OR json_extract(result,'$.id')=?",
                (object_id, object_id),
            ).fetchall()
        elif kind == "attachment_version":
            operations = db.execute(
                "SELECT id FROM operations WHERE json_extract(result,'$.version.id')=?",
                (object_id,),
            ).fetchall()
        else:
            return
        for row in operations:
            tombstone = json.dumps({"id": object_id, "deleted": True, "status": "purged"})
            db.execute(
                "INSERT INTO recycled_objects VALUES('request',?,?,'purged') ON CONFLICT(kind,id) DO UPDATE SET state='purged'",
                (row["id"], "purged-operation"),
            )
            db.execute(
                "UPDATE operations SET status='purged',request='{}',result=?,error=NULL,recent='[]' WHERE id=?",
                (tombstone, row["id"]),
            )

    def _cleanup(self, kind, object_id):
        if kind == "request":
            with self.store.connect() as db:
                row = db.execute("SELECT * FROM submissions WHERE id=?", (object_id,)).fetchone()
                if row and row["run_id"]:
                    db.execute(
                        "INSERT INTO recycled_objects VALUES('request',?,?,'purged') ON CONFLICT(kind,id) DO UPDATE SET state='purged'",
                        (row["run_id"], "purged-run"),
                    )
                    if db.execute(
                        "SELECT 1 FROM submissions WHERE status='preparing' AND parent=?",
                        (row["run_id"],),
                    ).fetchone():
                        return "待清理：子提交正在准备"
                    with self.store.evidence(row["run_id"], blocking=False):
                        path = self.store.path(row["run_id"])
                        if path.exists():
                            shutil.rmtree(path)
                    db.execute("DELETE FROM runs WHERE id=?", (row["run_id"],))
                if row:
                    db.execute("DELETE FROM submissions WHERE id=?", (object_id,))
                db.execute(
                    "UPDATE request_groups SET name='' WHERE id IN (SELECT group_id FROM request_links WHERE id=?) AND NOT EXISTS (SELECT 1 FROM request_links l LEFT JOIN recycled_objects r ON r.kind='request' AND r.id=l.id WHERE l.group_id=request_groups.id AND COALESCE(r.state,'active')!='purged')",
                    (object_id,),
                )
                db.execute(
                    "DELETE FROM management_names WHERE kind='group'  AND id IN (SELECT group_id FROM request_links WHERE id=?) AND NOT EXISTS (SELECT 1 FROM request_links l LEFT JOIN recycled_objects r ON r.kind='request' AND r.id=l.id WHERE l.group_id=management_names.id AND COALESCE(r.state,'active')!='purged')",
                    (object_id,),
                )
        elif kind == "attachment_version":
            with self.store.connect() as db:
                version = db.execute(
                    "SELECT * FROM attachment_versions WHERE id=?", (object_id,)
                ).fetchone()
                if not version:
                    return None
                if db.execute(
                    "SELECT 1 FROM submissions WHERE status='preparing' AND parent IS NULL AND json_extract(frozen,'$.bundle_id')=?",
                    (version["bundle_id"],),
                ).fetchone():
                    return "待清理：提交正在准备"
                bundle_id = version["bundle_id"]
                root = self.store.root / "bundles" / bundle_id
                if root.exists():
                    shutil.rmtree(root)
                db.execute("DELETE FROM bundles WHERE id=?", (bundle_id,))
                db.execute("DELETE FROM attachment_versions WHERE id=?", (object_id,))
        elif kind == "attachment":
            with self.store.connect() as db:
                if db.execute(
                    "SELECT 1 FROM attachment_versions WHERE attachment_id=?", (object_id,)
                ).fetchone():
                    return "待清理：附件版本仍在清理"
                db.execute("DELETE FROM attachments WHERE id=?", (object_id,))
                db.execute(
                    "DELETE FROM management_names WHERE kind='attachment' AND id=?", (object_id,)
                )
        elif kind == "dataset_version":
            with self.store.connect() as db:
                row = db.execute(
                    "SELECT * FROM dataset_sources WHERE id=?", (object_id,)
                ).fetchone()
                if row:
                    db.execute(
                        "DELETE FROM objects WHERE kind='author_parameters' AND id=? AND json_extract(config,'$.source')=?",
                        (row["dataset_id"], row["resolved"]),
                    )
                    db.execute(
                        "DELETE FROM objects WHERE kind='dataset' AND id=? AND json_extract(config,'$.resolved')=?",
                        (row["dataset_id"], row["resolved"]),
                    )
                    db.execute(
                        "DELETE FROM dataset_previews WHERE dataset_id=? AND json_extract(config,'$.resolved')=?",
                        (row["dataset_id"], row["resolved"]),
                    )
                    db.execute("DELETE FROM dataset_sources WHERE id=?", (object_id,))
                    shared = db.execute(
                        "SELECT 1 FROM dataset_sources WHERE resolved=?", (row["resolved"],)
                    ).fetchone()
                    if not shared:
                        from harbor_helper.persistence.files import read_json

                        base = self.store.root / "author-inputs"
                        if base.exists():
                            for cache in base.iterdir():
                                if (
                                    cache.is_dir()
                                    and not cache.is_symlink()
                                    and (cache / "source.json").is_file()
                                ) and (
                                    read_json(cache / "source.json").get("resolved")
                                    == row["resolved"]
                                ):
                                    shutil.rmtree(cache)

        elif kind == "dataset":
            with self.store.connect() as db:
                db.execute(
                    "DELETE FROM dataset_previews WHERE dataset_id=? OR dataset_id IN (SELECT id FROM dataset_aliases WHERE target=?)",
                    (object_id, object_id),
                )
                db.execute(
                    "UPDATE dataset_identities SET name='',source='',default_version=NULL WHERE id IN (SELECT id FROM dataset_aliases WHERE target=?)",
                    (object_id,),
                )
                for row in db.execute(
                    "SELECT id FROM dataset_aliases WHERE target=?", (object_id,)
                ).fetchall():
                    db.execute(
                        "DELETE FROM objects WHERE kind IN ('dataset','author_parameters') AND id=?",
                        (row["id"],),
                    )
                db.execute(
                    "DELETE FROM objects WHERE kind IN ('dataset','author_parameters') AND id=?",
                    (object_id,),
                )
                db.execute(
                    "DELETE FROM management_names WHERE kind='dataset' AND id=?", (object_id,)
                )
                # Identity/aliases retain only minimal permanent references, never names/config.
                db.execute(
                    "UPDATE dataset_identities SET name='',source='',default_version=NULL WHERE id=?",
                    (object_id,),
                )
        elif kind == "artifact":
            run_id, file_id = object_id.split(":", 1)
            # Resolve the original safe path while bypassing only this recycle marker.
            with self.store.evidence(run_id, blocking=False):
                from harbor_helper.service.materials import tombstone

                try:
                    path = self.app.artifact_cleanup_path(run_id, file_id)
                except ServiceError as error:
                    if error.status == 404:
                        return None
                    raise
                tombstone(
                    self.store,
                    run_id,
                    status="deleted",
                    name=path.relative_to(self.store.path(run_id)).as_posix(),
                )
                path.unlink(missing_ok=True)
                with self.store.connect() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO artifact_deletions VALUES(?,?,?,?)",
                        (run_id, file_id, "purge", time.time()),
                    )
        return None

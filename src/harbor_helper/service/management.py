"""Request grouping and dataset identity/version management."""

import json

from harbor_helper.service.management_data import available, reserve_name, state
from harbor_helper.service.permissions import management_admin
from harbor_helper.service.primitives import ServiceError


class Management:
    def __init__(self, app):
        import weakref

        self.app = weakref.proxy(app)
        self.data = app.data
        self.store = app.store

    def requests(self):
        with self.store.connect() as db:
            rows = db.execute("""SELECT l.*,g.name,g.creator_id FROM request_links l
                JOIN request_groups g ON g.id=l.group_id ORDER BY l.group_id,l.number""").fetchall()
            values = []
            for row in rows:
                if state(db, "request", row["id"]) != "active":
                    continue
                submission = db.execute(
                    "SELECT user_id,submitter,status,run_id,created FROM submissions WHERE id=?",
                    (row["id"],),
                ).fetchone()
                if submission:
                    detail = dict(submission)
                else:
                    operation = db.execute(
                        "SELECT user_id,status,created FROM operations WHERE id=?", (row["id"],)
                    ).fetchone()
                    if not operation or operation["status"] != "rejected":
                        continue
                    detail = {
                        **dict(operation),
                        "run_id": None,
                        "submitter": self.data.user(operation["user_id"])["username"],
                    }
                values.append(
                    {
                        **dict(row),
                        **detail,
                        "display_name": row["name"] or "未命名 · " + row["group_id"][4:12],
                    }
                )
        return {"requests": values}

    def rename(self, actor, group_id, name):
        if not isinstance(name, str) or len(name) > 128:
            raise ServiceError("group_name", "组名最多128字符")
        with self.store.control(), self.store.connect() as db:
            row = db.execute("SELECT * FROM request_groups WHERE id=?", (group_id,)).fetchone()
            if not row:
                raise ServiceError("group_missing", "请求组不存在", 404)
            if actor["id"] != row["creator_id"]:
                management_admin(actor, "recycle_all")
            elif actor.get("access_credential_id"):
                from harbor_helper.service.policy import authorize

                authorize(actor, "rename_group")
            name = reserve_name(db, "group", group_id, name)
            db.execute("UPDATE request_groups SET name=? WHERE id=?", (name, group_id))
        return {"id": group_id, "name": name}

    def datasets(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM dataset_identities ORDER BY name,id").fetchall()
            result = []
            for row in rows:
                if (
                    state(db, "dataset", row["id"]) != "active"
                    or db.execute(
                        "SELECT 1 FROM dataset_aliases WHERE id=?", (row["id"],)
                    ).fetchone()
                ):
                    continue
                versions = []
                for version in db.execute(
                    "SELECT * FROM dataset_sources WHERE dataset_id=? ORDER BY number DESC",
                    (row["id"],),
                ).fetchall():
                    if state(db, "dataset_version", version["id"]) != "active":
                        continue
                    config = json.loads(version["config"])
                    versions.append(
                        {k: version[k] for k in ("id", "number", "resolved", "created")}
                        | {
                            "tasks": config.get("tasks", []),
                            "parameters": self.app.configuration.author_parameters(
                                row["id"], version["resolved"]
                            ),
                        }
                    )
                duplicates = sum(r["source"] == row["source"] for r in rows) > 1
                result.append({**dict(row), "versions": versions, "needs_merge": duplicates})
            return {"datasets": result}

    def default(self, actor, dataset_id, version_id, team_default=False):
        management_admin(actor, "datasets_manage")
        with self.store.control(), self.store.connect() as db:
            available(db, "dataset", dataset_id)
            available(db, "dataset_version", version_id)
            if not db.execute(
                "SELECT 1 FROM dataset_sources WHERE dataset_id=? AND id=?",
                (dataset_id, version_id),
            ).fetchone():
                raise ServiceError("dataset_version_missing", "版本不属于该数据集", 404)
            db.execute(
                "UPDATE dataset_identities SET default_version=? WHERE id=?",
                (version_id, dataset_id),
            )
        if team_default:
            self.app.configuration.save_settings({"default_dataset_id": dataset_id})
        return {"updated": True}

    def merge_preview(self, actor, source, target):
        management_admin(actor, "datasets_manage")
        if source == target:
            raise ServiceError("merge_target", "请选择两个不同的同源数据集")
        with self.store.connect() as db:
            identities = [
                db.execute("SELECT * FROM dataset_identities WHERE id=?", (i,)).fetchone()
                for i in (source, target)
            ]
            if not all(identities) or identities[0]["source"] != identities[1]["source"]:
                raise ServiceError("merge_source", "只能合并同一作者/包名的数据集")
            for i in (source, target):
                available(db, "dataset", i)
                if db.execute("SELECT 1 FROM dataset_aliases WHERE id=?", (i,)).fetchone():
                    raise ServiceError("merge_alias", "请选择实际目标对象", 409)
            versions = [
                dict(r)
                for r in db.execute(
                    "SELECT id,dataset_id,resolved FROM dataset_sources WHERE dataset_id IN (?,?)",
                    (source, target),
                )
            ]
            parameters = [
                dict(r)
                for r in db.execute(
                    "SELECT id,version,config FROM objects WHERE kind='author_parameters' AND id IN (?,?) ORDER BY id,version",
                    (source, target),
                )
            ]
            defaults = {i["id"]: i["default_version"] for i in identities}
            drafts = [
                dict(r)
                for r in db.execute(
                    "SELECT id,version,config FROM objects WHERE kind='dataset' AND id IN (?,?) AND (json_extract(config,'$.resolved') IS NULL OR json_extract(config,'$.status')!='verified') ORDER BY id,version",
                    (source, target),
                )
            ]
            settings = self.app.configuration.settings()
            from harbor_helper.persistence.files import digest

            return {
                "source": source,
                "target": target,
                "versions": versions,
                "parameters": parameters,
                "defaults": defaults,
                "team_default": settings.get("default_dataset_id"),
                "drafts": drafts,
                "revision": digest(
                    [versions, parameters, defaults, drafts, settings.get("default_dataset_id")]
                ),
            }

    def merge(self, actor, source, target, revision, parameter_choices):
        management_admin(actor, "datasets_manage")
        with self.store.control():
            preview = self.merge_preview(actor, source, target)
            if preview["revision"] != revision:
                raise ServiceError("merge_changed", "合并范围已变化，请刷新预览", 409)
            # Each retained parameter revision is explicitly selectable; no last-write-wins.
            by_source = {}
            for r in preview["parameters"]:
                value = json.loads(r["config"])
                if value.get("source"):
                    by_source.setdefault(value["source"], []).append(r)
            for resolved, candidates in by_source.items():
                chosen = parameter_choices.get(resolved)
                if (
                    len(
                        {
                            json.dumps(json.loads(c["config"]).get("values", {}), sort_keys=True)
                            for c in candidates
                        }
                    )
                    > 1
                    and not chosen
                ):
                    raise ServiceError(
                        "merge_parameters", "存在参数冲突，请明确选择每个摘要使用的原修订", 409
                    )
                if chosen and not any(
                    c["id"] == chosen.get("id") and c["version"] == chosen.get("version")
                    for c in candidates
                ):
                    raise ServiceError("merge_parameters", "参数修订不在预览范围")
            with self.store.connect() as db:
                from harbor_helper.service.management_data import allocate

                default_source = db.execute(
                    "SELECT resolved FROM dataset_sources WHERE id=?",
                    (preview["defaults"].get(source),),
                ).fetchone()
                for version in preview["versions"]:
                    if version["dataset_id"] != source:
                        continue
                    old = db.execute(
                        "SELECT * FROM dataset_sources WHERE id=?", (version["id"],)
                    ).fetchone()
                    exists = db.execute(
                        "SELECT id FROM dataset_sources WHERE dataset_id=? AND resolved=?",
                        (target, old["resolved"]),
                    ).fetchone()
                    if not exists:
                        db.execute(
                            "UPDATE dataset_sources SET dataset_id=?,number=? WHERE id=?",
                            (target, allocate(db, "dataset", target), old["id"]),
                        )
                db.execute("INSERT INTO dataset_aliases VALUES(?,?)", (source, target))
                db.execute("UPDATE dataset_aliases SET target=? WHERE target=?", (target, source))
                db.execute("DELETE FROM management_names WHERE kind='dataset' AND id=?", (source,))
                # Preserve originals; selected copies are new target revisions.
                for resolved, choice in parameter_choices.items():
                    selected = next(
                        c
                        for c in by_source[resolved]
                        if c["id"] == choice["id"] and c["version"] == choice["version"]
                    )
                    number = db.execute(
                        "SELECT COALESCE(MAX(version),0)+1 FROM objects WHERE kind='author_parameters' AND id=?",
                        (target,),
                    ).fetchone()[0]
                    value = json.loads(selected["config"])
                    db.execute(
                        "INSERT INTO objects VALUES(?,?,?,?)",
                        ("author_parameters", target, number, json.dumps(value)),
                    )
                if preview["team_default"] == source:
                    mapped = db.execute(
                        "SELECT id FROM dataset_sources WHERE dataset_id=? AND resolved=?",
                        (target, default_source[0] if default_source else None),
                    ).fetchone()
                    db.execute(
                        "UPDATE dataset_identities SET default_version=? WHERE id=?",
                        (mapped[0] if mapped else None, target),
                    )
                    db.execute(
                        "UPDATE configuration_settings SET config=json_set(config,'$.default_dataset_id',?) WHERE id=1",
                        (target if mapped else None,),
                    )
        return {"merged": True, "target": target}

    def versions(self, actor, dataset_id):
        management_admin(actor, "datasets_manage")
        from harbor_helper.service.sources import source_call

        with self.store.connect() as db:
            available(db, "dataset", dataset_id)
            row = db.execute(
                "SELECT source FROM dataset_identities WHERE id=?", (dataset_id,)
            ).fetchone()
            if not row:
                raise ServiceError("dataset_missing", "数据集不存在", 404)
        return source_call(row["source"], key=self.app.configuration.hub_key(), action="versions")

    def preview(self, actor, dataset_id, digest):
        import re
        import time
        import uuid

        from harbor_helper.service.sources import source_call

        management_admin(actor, "datasets_manage")
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ServiceError("dataset_digest", "请选择不可变来源摘要")
        with self.store.connect() as db:
            available(db, "dataset", dataset_id)
            identity = db.execute(
                "SELECT * FROM dataset_identities WHERE id=?", (dataset_id,)
            ).fetchone()
            if not identity:
                raise ServiceError("dataset_missing", "数据集不存在", 404)
        hub = self.app.configuration.hub_status()
        # Validate dataset type and non-yanked membership, including supplemental digests.
        listed = self.versions(actor, dataset_id)
        reference = identity["source"] + "@" + digest
        metadata = source_call(reference, key=self.app.configuration.hub_key(), action="preview")
        if metadata["resolved"] != reference:
            raise ServiceError("dataset_changed", "来源返回摘要不一致", 409)
        value = {
            **self.data.object("dataset", dataset_id),
            **metadata,
            "reference": reference,
            "status": "verified",
            "source_version": hub["version"] if hub["mode"] == "team" else None,
        }
        preview_id = "preview-" + uuid.uuid4().hex
        with self.store.control(), self.store.connect() as db:
            available(db, "dataset", dataset_id)
            db.execute(
                "INSERT INTO dataset_previews VALUES(?,?,?,?,?)",
                (preview_id, dataset_id, value["source_version"], json.dumps(value), time.time()),
            )
        return {
            "id": preview_id,
            "dataset_id": dataset_id,
            "resolved": reference,
            "tasks": metadata["tasks"],
            "listed": any(v["digest"] == digest for v in listed["versions"]),
        }

    def confirm(self, actor, preview_id):
        from harbor_helper.service.sources import source_call

        management_admin(actor, "datasets_manage")
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM dataset_previews WHERE id=?", (preview_id,)).fetchone()
            if not row:
                raise ServiceError("preview_missing", "请先预览固定版本", 404)
            available(db, "dataset", row["dataset_id"])
            value = json.loads(row["config"])
        result = source_call(
            value["resolved"],
            key=self.app.configuration.hub_key(row["source_version"]),
            action="preview",
        )
        if result["resolved"] != value["resolved"] or result["tasks"] != value["tasks"]:
            raise ServiceError("dataset_changed", "预览与确认内容不一致，请重新预览", 409)
        with self.store.control():
            self.app.configuration.persist("dataset", value)
        return {"confirmed": True, "resolved": value["resolved"]}

"""Persistent input preparation and evidence-retention maintenance."""

import shutil
import time

from harbor_helper.execution.config import load_team
from harbor_helper.persistence import statuses as lifecycle_status
from harbor_helper.persistence.files import write_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.security.master_key import MasterUnavailable
from harbor_helper.service.data import ServiceData
from harbor_helper.service.evidence import Evidence
from harbor_helper.service.primitives import ServiceError


def prepare_one(store):
    """Single scheduler prepares immutable inputs without holding global control lock.

    target_id is persisted before IO; restart reconciles a committed run or safely
    repeats only input preparation. runs.submit atomically gates queue publication.
    """
    data = ServiceData(store)
    data.master_keys.current()
    with store.connect() as db:
        ids = [
            r[0]
            for r in db.execute(
                "SELECT id FROM submissions WHERE status='preparing' ORDER BY created LIMIT 1"
            )
        ]
    if not ids:
        return
    row = data.submission(ids[0])
    run_id = row["target_id"]
    if row["cancel"]:
        with store.control(), store.connect() as db:
            db.execute("UPDATE submissions SET status='cancelled' WHERE id=?", (row["id"],))
        return
    with store.connect() as db:
        published = db.execute("SELECT 1 FROM runs WHERE id=?", (run_id,)).fetchone()
    if published:
        with store.control(), store.connect() as db:
            db.execute(
                f"UPDATE submissions SET status={lifecycle_status.READY!r},run_id=? WHERE id=?",
                (run_id, row["id"]),
            )
            if row["cancel"]:
                store.update(run_id, cancel=1)
        return
    path = store.root / "runs" / run_id
    if path.exists():
        shutil.rmtree(path)
    frozen = row["frozen"]
    from harbor_helper.execution.runs import submit

    try:
        submit(
            store,
            load_team(store),
            frozen["effective"],
            bundle=store.root / "bundles" / frozen["bundle_id"] if frozen["bundle_id"] else None,
            parent=row["parent"],
            service=frozen["service"],
            run_id=run_id,
            start_supervisor=False,
        )
        with store.control(), store.connect() as db:
            current = data.submission(row["id"])
            if current["cancel"]:
                store.update(run_id, cancel=1)
            db.execute(
                f"UPDATE submissions SET status={lifecycle_status.READY!r},run_id=? WHERE id=?",
                (run_id, row["id"]),
            )
    except MasterUnavailable:
        raise
    except Exception as error:  # noqa: BLE001 - third-party source errors may carry credentials
        from harbor_helper.execution.author_inputs import AuthorInputError

        if isinstance(error, (AuthorInputError, ServiceError)):
            message = f"{error.code}: {error}"
            if isinstance(error, AuthorInputError) and row["operation"].split(":", 1)[0] == "rerun":
                message += "；原条件重跑保留冻结参数，请在父实验选择修复后重试，或恢复本次失败提交"
        elif isinstance(error, ValueError) and (
            "bundle" in str(error).lower() or "snapshot" in str(error).lower()
        ):
            message = "input_snapshot: 固定输入或实验包不可用；请修改输入后新提交"
        else:
            message = (
                "input_preparation: 准备失败；管理员检查数据集权限、运行环境与实验包，修复后新提交"
            )
        with store.connect() as db:
            if isinstance(error, AuthorInputError):
                frozen["service"]["author_input_issues"] = error.issues
                # Preserve the fixed source digest already recorded during download.
                latest = data.submission(row["id"])["frozen"]
                latest["service"]["author_input_issues"] = error.issues
                db.execute(
                    "UPDATE submissions SET frozen=? WHERE id=?",
                    (__import__("json").dumps(latest), row["id"]),
                )
            db.execute(
                f"UPDATE submissions SET status=CASE WHEN cancel=1 THEN {lifecycle_status.CANCELLED!r} ELSE {lifecycle_status.FAILED!r} END,error=? WHERE id=?",
                (
                    message,
                    row["id"],
                ),
            )


def maintenance(store):
    """Expire retained evidence only after resources and audit are confirmed safe."""
    data = ServiceData(store)
    limits = data.limits()
    for row in store.runs():
        if (
            row["status"] not in TERMINAL
            or row.get("audit_status") != lifecycle_status.CLEAN
            or not row["finished"]
        ):
            continue
        with store.evidence(row["id"]):
            path = store.path(row["id"])
            age = time.time() - row["finished"]
            from harbor_helper.service.materials import tombstone

            if age > limits["artifact_retention_days"] * 86400:
                tombstone(store, row["id"], status="expired", category_filter="artifact")
                for folder in (path / "harbor").glob("*/*/artifacts"):
                    if folder.is_dir() and not folder.is_symlink():
                        shutil.rmtree(folder)
            if age > limits["log_retention_days"] * 86400 and not (path / "archived.json").exists():
                report = Evidence(data).safe_report(row["id"])
                if report:
                    write_json(path / "safe-report.json", report)
                tombstone(store, row["id"], status="expired")
                shutil.rmtree(path / "harbor", ignore_errors=True)
                (path / "worker.log").unlink(missing_ok=True)
                write_json(
                    path / "archived.json",
                    {"time": time.time(), "reason": "Configured raw evidence retention"},
                )
    data.prune_credentials()

"""Persistent input preparation and evidence-retention maintenance."""

import shutil
import time

from harbor_helper.execution.config import load_team
from harbor_helper.persistence.files import write_json
from harbor_helper.persistence.store import TERMINAL
from harbor_helper.service.application import Application
from harbor_helper.service.data import ServiceError


def prepare_one(store):
    """Single scheduler prepares immutable inputs without holding global control lock.

    target_id is persisted before IO; restart reconciles a committed run or safely
    repeats only input preparation. runs.submit atomically gates queue publication.
    """
    app = Application(store)
    with store.connect() as db:
        ids = [
            r[0]
            for r in db.execute(
                "SELECT id FROM submissions WHERE status='preparing' ORDER BY created LIMIT 1"
            )
        ]
    if not ids:
        return
    row = app.data.submission(ids[0])
    run_id = row["target_id"]
    if any(r["id"] == run_id for r in store.runs()):
        with store.control(), store.connect() as db:
            db.execute(
                "UPDATE submissions SET status='ready',run_id=? WHERE id=?", (run_id, row["id"])
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
            current = app.data.submission(row["id"])
            if current["cancel"]:
                store.update(run_id, cancel=1)
            db.execute(
                "UPDATE submissions SET status='ready',run_id=? WHERE id=?", (run_id, row["id"])
            )
    except Exception as error:  # noqa: BLE001 - third-party source errors may carry credentials
        if isinstance(error, ServiceError):
            message = f"{error.code}: {error}"
        elif isinstance(error, ValueError) and "image" in str(error).lower():
            message = (
                "runtime_missing: 固定运行镜像不可用；管理员检查环境并重新验证，成员修改后新提交"
            )
        elif isinstance(error, ValueError) and (
            "bundle" in str(error).lower() or "snapshot" in str(error).lower()
        ):
            message = "input_snapshot: 固定输入或实验包不可用；请修改输入后新提交"
        else:
            message = (
                "input_preparation: 准备失败；管理员检查数据集权限、运行环境与实验包，修复后新提交"
            )
        with store.connect() as db:
            db.execute(
                "UPDATE submissions SET status=CASE WHEN cancel=1 THEN 'cancelled' ELSE 'failed' END,error=? WHERE id=?",
                (
                    message,
                    row["id"],
                ),
            )


def maintenance(store):
    """Expire retained evidence only after resources and audit are confirmed safe."""
    app = Application(store)
    limits = app.data.limits()
    for row in store.runs():
        if (
            row["status"] not in TERMINAL
            or row.get("audit_status") != "clean"
            or not row["finished"]
        ):
            continue
        path = store.path(row["id"])
        age = time.time() - row["finished"]
        if age > limits["artifact_retention_days"] * 86400:
            for folder in (path / "harbor").glob("*/*/artifacts"):
                if folder.is_dir() and not folder.is_symlink():
                    shutil.rmtree(folder)
        if age > limits["log_retention_days"] * 86400 and not (path / "archived.json").exists():
            report = app.safe_report(row["id"])
            if report:
                write_json(path / "safe-report.json", report)
            shutil.rmtree(path / "harbor", ignore_errors=True)
            (path / "worker.log").unlink(missing_ok=True)
            write_json(
                path / "archived.json",
                {"time": time.time(), "reason": "Configured raw evidence retention"},
            )
    app.data.prune_credentials()

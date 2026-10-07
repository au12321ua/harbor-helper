import math
from collections import defaultdict

from harbor_helper.storage import read_json, write_json


def report(store, run_id):
    path = store.path(run_id)
    manifest = read_json(path / "manifest.json")
    expected = {t["package"].split("/", 1)[-1]: t for t in manifest["source"]["tasks"]}
    rows = []
    for p in sorted((path / "harbor").glob("*/*/result.json")):
        try:
            result = read_json(p)
            task = result["task_name"].split("/", 1)[-1]
            reward = (result.get("verifier_result") or {}).get("rewards")
            exception = result.get("exception_info")
            exit_file = p.parent / "agent" / "exit-code.txt"
            if exit_file.exists() and exit_file.read_text().strip() not in {"", "0"}:
                exception = exception or {
                    "exception_type": "AgentNonZeroExit",
                    "exception_message": exit_file.read_text().strip(),
                }
            step_errors = [
                s.get("exception_info")
                for s in result.get("step_results") or []
                if s.get("exception_info")
            ]
            valid = isinstance(reward, dict) and bool(reward) and not exception and not step_errors
            valid = valid and all(
                isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                for v in reward.values()
            )
            rows.append(
                {
                    "task": task,
                    "trial": result.get("trial_name"),
                    "valid": valid,
                    "agent_exit_code": exit_file.read_text().strip()
                    if exit_file.exists()
                    else None,
                    "framework_exception": result.get("exception_info"),
                    "rewards": reward if valid else None,
                    "observed_rewards": reward,
                    "exception": exception
                    or step_errors
                    or (None if valid else {"exception_type": "MissingReward"}),
                    "evidence": str(p.parent),
                    "agent_info": result.get("agent_info"),
                    "artifacts": [
                        str(f) for f in (p.parent / "artifacts").rglob("*") if f.is_file()
                    ],
                }
            )
        except (ValueError, KeyError, TypeError) as e:
            rows.append(
                {
                    "task": "unknown",
                    "valid": False,
                    "rewards": None,
                    "exception": {
                        "exception_type": "MalformedTrialResult",
                        "exception_message": str(e),
                    },
                    "evidence": str(p),
                }
            )
    by_task = defaultdict(list)
    for row in rows:
        by_task[row["task"]].append(row)
    tasks = []
    for name in expected:
        attempts = by_task[name]
        valid = [a for a in attempts if a["valid"]]
        metrics = sorted({k for a in valid for k in a["rewards"]})
        means = {
            k: sum(a["rewards"][k] for a in valid if k in a["rewards"])
            / sum(k in a["rewards"] for a in valid)
            for k in metrics
        }
        tasks.append(
            {
                "task": name,
                "expected_attempts": manifest["effective"]["attempts"],
                "valid_attempts": len(valid),
                "observed_attempts": len(attempts),
                "mean_rewards": means or None,
                "attempts": attempts,
            }
        )
    valid_count = sum(t["valid_attempts"] for t in tasks)
    expected_count = len(tasks) * manifest["effective"]["attempts"]
    complete = (
        valid_count == expected_count
        and len(rows) == expected_count
        and all(
            t["valid_attempts"] == t["expected_attempts"]
            and t["observed_attempts"] == t["expected_attempts"]
            for t in tasks
        )
    )
    if store.get(run_id)["status"] == "succeeded" and not complete:
        store.update(run_id, status="failed", reason="Result audit found invalid/missing attempts")
    result = {
        "run_id": run_id,
        "status": store.get(run_id)["status"],
        "reason": store.get(run_id)["reason"],
        "complete": complete,
        "expected_attempts": expected_count,
        "valid_attempts": valid_count,
        "invalid_attempts": sum(not a["valid"] for a in rows),
        "missing_attempts": sum(
            max(0, t["expected_attempts"] - t["observed_attempts"]) for t in tasks
        ),
        "source": manifest["source"],
        "tasks": tasks,
        "unexpected_trials": [r for r in rows if r["task"] not in expected],
        "manifest": str(path / "manifest.json"),
        "raw_results": str(path / "harbor"),
        "worker_log": str(path / "worker.log"),
    }
    write_json(path / "report.json", result)
    return result


def compare(store, left, right):
    a, b = (read_json(store.path(i) / "manifest.json") for i in (left, right))
    reasons = []
    if a["source"] != b["source"]:
        reasons.append("Dataset/task/scoring source differs")
    keys = (
        "agent",
        "model",
        "attempts",
        "concurrency",
        "wall_seconds",
        "runtime_image",
        "max_cpus_per_trial",
        "max_memory_mb_per_trial",
    )
    changes = {
        k: {"left": a["effective"].get(k), "right": b["effective"].get(k)}
        for k in keys
        if a["effective"].get(k) != b["effective"].get(k)
    }
    reasons.extend(f"Experiment condition differs: {k}" for k in changes)
    for k in ("harbor_version", "image_id"):
        if a[k] != b[k]:
            reasons.append(f"Actual runtime version differs: {k}")
    ra, rb = report(store, left), report(store, right)
    if not ra["complete"] or not rb["complete"]:
        reasons.append("Incomplete/exceptional attempts: no aggregate improvement conclusion")
    if any(store.get(i)["status"] != "succeeded" for i in (left, right)):
        reasons.append("Both runs must succeed")
    deltas = []
    for ta, tb in zip(ra["tasks"], rb["tasks"]):
        ma, mb = ta["mean_rewards"] or {}, tb["mean_rewards"] or {}
        if ta["task"] != tb["task"] or set(ma) != set(mb):
            reasons.append("Reward schema/task differs")
            continue
        deltas.append(
            {"task": ta["task"], "left": ma, "right": mb, "delta": {k: mb[k] - ma[k] for k in ma}}
        )
    aggregate = None
    if not reasons and deltas:
        metrics = set.intersection(*(set(d["delta"]) for d in deltas))
        aggregate = {k: sum(d["delta"][k] for d in deltas) / len(deltas) for k in metrics}
    return {
        "left": left,
        "right": right,
        "comparable": not reasons,
        "reasons": reasons,
        "config_changes": changes,
        "bundle_change": {"left": a["bundle_digest"], "right": b["bundle_digest"]},
        "tasks": deltas,
        "mean_task_delta": aggregate,
    }

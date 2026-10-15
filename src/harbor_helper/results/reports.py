import math
import re
from collections import defaultdict
from datetime import datetime

from harbor_helper.persistence.files import read_json, write_json


def environment_observations(path):
    observations = []
    for evidence in sorted((path / "harbor").glob("*/*/helper-environment-*.json")):
        try:
            value = read_json(evidence)
            if isinstance(value, dict):
                observations.append(value)
        except (ValueError, OSError):
            observations.append({"images": "unknown"})
    return observations or "unknown"


def trial_diagnosis(result, trial_dir, cfg):
    """Bounded structured evidence; never copy command output into diagnostic hints."""
    phases = []
    for name in ("environment_setup", "agent_setup", "agent_execution", "verifier"):
        timing = result.get(name)
        seconds = None
        if isinstance(timing, dict) and timing.get("started_at") and timing.get("finished_at"):
            try:
                seconds = (
                    datetime.fromisoformat(timing["finished_at"])
                    - datetime.fromisoformat(timing["started_at"])
                ).total_seconds()
            except (ValueError, TypeError):
                pass
        phases.append(
            {
                "phase": name,
                "reached": isinstance(timing, dict) and bool(timing.get("started_at")),
                "seconds": seconds,
            }
        )
    compose = []
    for evidence in sorted(trial_dir.glob("helper-phases-*.json")):
        try:
            for entry in read_json(evidence):
                if entry.get("phase") in {"build", "pull", "up", "down"}:
                    seconds = entry.get("seconds")
                    compose.append(
                        {
                            "phase": entry["phase"],
                            "status": entry.get("status")
                            if entry.get("status")
                            in {"running", "completed", "failed", "interrupted"}
                            else "unknown",
                            "seconds": seconds
                            if type(seconds) in {int, float}
                            and math.isfinite(seconds)
                            and seconds >= 0
                            else None,
                        }
                    )
        except (ValueError, OSError, TypeError, AttributeError):
            pass
    installation = None
    try:
        decision = read_json(trial_dir / "agent" / "install-decision.json")
        if isinstance(decision, dict):
            installation = {
                "missing_dependencies": [
                    tool
                    for tool in decision.get("missing_dependencies", [])
                    if tool in {"curl", "bash", "cat", "node", "npm", "sh", "tee", "stdbuf"}
                ],
                "reused": decision.get("reused") is True,
            }
            if decision.get("strategy") == "offline-npm-binary-v1":
                installation.update(
                    strategy="offline-npm-binary-v1",
                    stage=decision.get("stage")
                    if decision.get("stage")
                    in {"public_tool_preparation", "offline_tool_installation", "ready"}
                    else "unknown",
                    status=decision.get("status")
                    if decision.get("status") in {"running", "completed", "interrupted", "failed"}
                    else "unknown",
                    cache_hit=decision.get("cache_hit") is True,
                )
                if decision.get("preparation_error_type") in {
                    "HTTPError",
                    "URLError",
                    "TimeoutError",
                    "ValueError",
                    "OSError",
                    "KeyError",
                    "unknown",
                }:
                    installation["preparation_error_type"] = decision["preparation_error_type"]
                seconds = decision.get("preparation_seconds")
                if type(seconds) in {int, float} and math.isfinite(seconds) and seconds >= 0:
                    installation["preparation_seconds"] = seconds
                material = decision.get("material") or {}
                if isinstance(material, dict):
                    for key, pattern in {
                        "version": r"\d+\.\d+\.\d+",
                        "binary_sha256": r"[0-9a-f]{64}",
                        "source": r"https://registry\.npmjs\.org/opencode-linux-[a-z0-9-]+/-/opencode-linux-[a-z0-9-]+-\d+\.\d+\.\d+\.tgz",
                    }.items():
                        value = material.get(key)
                        if isinstance(value, str) and re.fullmatch(pattern, value):
                            installation[key] = value
    except (ValueError, OSError, TypeError):
        pass
    error = result.get("exception_info") or {}
    error_type = error.get("exception_type", "")
    phase = next((p["phase"] for p in reversed(phases) if p["reached"]), "unknown")
    if "author environment network_mode=no-network" in error.get("exception_message", ""):
        hint = "作者环境禁止联网，且缺少固定OpenCode安装依赖；未覆盖作者策略。请使用修复后重试为缺策略的旧受理补离线工具准备。未执行模型。"
    elif error_type == "EnvironmentStartTimeoutError":
        hint = "环境启动超过作者时限×冻结倍数；检查构建/拉取/启动记录和整体运行时长。up包含入口程序与Compose健康等待，不能据此单独认定健康检查失败。"
    elif phase == "agent_setup" and error:
        hint = "代理准备失败，尚未推理。检查工具准备/离线安装阶段、作者网络策略及已审计日志；启动等待倍数不延长代理安装阶段。新工具策略在任务网络外下载固定公共材料，再由Harbor上传；不会开放任务公网。"
    elif error:
        hint = "执行异常；查看已审计日志及各阶段记录。"
    else:
        hint = "阶段耗时为可观察证据；未到达的阶段不代表零耗时。"
    return {
        "phase": phase,
        "model_status": "not_reached"
        if cfg.get("agent") == "opencode"
        and not any(p["phase"] == "agent_execution" and p["reached"] for p in phases)
        else "unknown",
        "hint": hint,
        "phases": phases,
        "compose": compose or "unknown",
        "startup_multiplier": cfg.get("environment_build_timeout_multiplier", 1),
        "agent_installation": installation,
    }


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
                    "diagnosis": trial_diagnosis(result, p.parent, manifest["effective"]),
                    "phase_timings": {
                        k: result.get(k) or "unknown"
                        for k in ("environment_setup", "agent_setup", "agent_execution", "verifier")
                    },
                    "artifacts": [
                        str(f) for f in (p.parent / "artifacts").rglob("*") if f.is_file()
                    ],
                }
            )
        except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as e:
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
        "harbor_version": manifest.get("harbor_version", "unknown"),
        "environment_observations": environment_observations(path),
        "tasks": tasks,
        "unexpected_trials": [r for r in rows if r["task"] not in expected],
        "manifest": str(path / "manifest.json"),
        "raw_results": str(path / "harbor"),
        "worker_log": str(path / "worker.log"),
    }
    write_json(path / "report.json", result)
    return result


def compare(store, left, right, published_reports=None):
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
        "environment_build_timeout_multiplier",
        "agent_tool_preparation",
        "author_env",
        "max_cpus_per_trial",
        "max_memory_mb_per_trial",
    )
    # Missing in a historical snapshot means Harbor's actual multiplier 1,
    # never the current new-submission default. Normalize only these local copies.
    conditions = [
        {
            **m["effective"],
            "author_env": m["effective"].get("author_env", {}),
            "environment_build_timeout_multiplier": m["effective"].get(
                "environment_build_timeout_multiplier", 1
            ),
            "agent_tool_preparation": m["effective"].get("agent_tool_preparation", "in-task-npm"),
        }
        for m in (a, b)
    ]
    changes = {
        k: {"left": conditions[0].get(k), "right": conditions[1].get(k)}
        for k in keys
        if conditions[0].get(k) != conditions[1].get(k)
    }
    reasons.extend(f"Experiment condition differs: {k}" for k in changes)
    if a.get("harbor_version") != b.get("harbor_version"):
        reasons.append("Actual runtime version differs: harbor_version")
    ra, rb = (
        published_reports
        if published_reports is not None
        else (report(store, left), report(store, right))
    )
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
        "environment_observations": {
            "left": ra.get("environment_observations", "unknown"),
            "right": rb.get("environment_observations", "unknown"),
        },
        "bundle_change": {"left": a["bundle_digest"], "right": b["bundle_digest"]},
        "attachment_inputs": {
            side: {
                "kind": "versioned"
                if m.get("service", {}).get("attachment_version_id")
                else "none",
                "attachment_version_id": m.get("service", {}).get("attachment_version_id"),
                "bundle_id": m.get("service", {}).get("bundle_id"),
                "digest": m.get("bundle_digest"),
            }
            for side, m in (("left", a), ("right", b))
        },
        "tasks": deltas,
        "mean_task_delta": aggregate,
    }

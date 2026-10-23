"""Scoring contract and run summaries (06 sections 2, 5 and 7).

Pure functions over trial records: web pages, the API and exports all call
``summarize`` so they report the same counts. Only trials in state ``scored``
(a legal number with reward_valid) enter the statistics; a real 0 is a sample,
an invalid reward is never one even when a number exists.
"""

import math
from collections import defaultdict
from dataclasses import dataclass

from maestro.domain.states import TrialState

CONTRACT_VERSION = 1

# Used when the dataset version declares no confirmed contract. ``passed`` needs an
# explicit threshold (never "score > 0"); Harbor verifiers write 1 for a solved task.
DEFAULT_CONTRACT = {
    "contract_version": CONTRACT_VERSION,
    "source": "platform_default",
    "metric_id": "reward",
    "name": "Reward",
    "unit": None,
    "direction": "higher_is_better",
    "passed": {"rule": "threshold", "threshold": 1.0},
    "task_aggregation": "mean_of_scored_repetitions",
    "bench_aggregation": "macro_mean_of_task_means",
    "count_as_failure": [],
}

_DIRECTIONS = {"higher_is_better", "lower_is_better"}


def contract_for(manifest: dict | None) -> dict:
    """The dataset version's declared contract when well formed, else the default."""
    declared = (manifest or {}).get("scoring_contract")
    if not isinstance(declared, dict):
        return dict(DEFAULT_CONTRACT)
    contract = {**DEFAULT_CONTRACT, **declared, "source": "dataset_version"}
    passed = contract.get("passed")
    if contract.get("direction") not in _DIRECTIONS or not (
        passed is None
        or (
            isinstance(passed, dict)
            and passed.get("rule") == "threshold"
            and _number(passed.get("threshold"))
        )
    ):
        return dict(DEFAULT_CONTRACT)
    return contract


def _number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class TrialRecord:
    task_key: str
    state: str
    raw_score: float | None = None
    failure_cause: str | None = None
    attempts: int = 0
    usage: dict | None = None


def passed(contract: dict, score: float) -> bool | None:
    rule = contract.get("passed")
    if not rule:
        return None
    if contract["direction"] == "lower_is_better":
        return score <= rule["threshold"]
    return score >= rule["threshold"]


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def sample_stddev(values: list[float]) -> float | None:
    """n - 1 denominator; fewer than two samples have no spread (not 0)."""
    if len(values) < 2:
        return None
    centre = sum(values) / len(values)
    return math.sqrt(sum((v - centre) ** 2 for v in values) / (len(values) - 1))


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _usage(trials: list[TrialRecord]) -> dict:
    """Known totals plus how many trials reported nothing (06 section 7)."""
    totals: dict[str, float] = defaultdict(float)
    known = 0
    for trial in trials:
        if trial.state == TrialState.NOT_STARTED:
            continue
        values = {k: v for k, v in (trial.usage or {}).items() if _number(v)}
        if values:
            known += 1
            for key, value in values.items():
                totals[key] += value
    started = sum(1 for x in trials if x.state != TrialState.NOT_STARTED)
    return {"known_trials": known, "unknown_trials": started - known, "known_totals": totals}


def summarize(
    trials: list[TrialRecord], contract: dict, bench_task_count: int | None = None
) -> dict:
    """06 section 5. At a terminal run planned = scored + count_as_failure + excluded +
    unfinished; while running, active and queued trials make up the rest."""
    states = [x.state for x in trials]
    scored = [x for x in trials if x.state == TrialState.SCORED and _number(x.raw_score)]
    values = [x.raw_score for x in scored]
    has_pass_rule = bool(contract.get("passed"))
    passed_count = sum(1 for x in scored if passed(contract, x.raw_score)) if has_pass_rule else 0
    planned = len(trials)
    count_as_failure = 0  # Non-default extension (06 section 1); not offered yet.
    excluded = states.count(TrialState.EXECUTION_ERROR)
    unfinished = sum(
        states.count(s)
        for s in (TrialState.NOT_STARTED, TrialState.CANCELLED, TrialState.INTERRUPTED)
    )
    active = sum(
        states.count(s) for s in (TrialState.PREPARING, TrialState.EXECUTING, TrialState.VERIFYING)
    )
    queued = states.count(TrialState.QUEUED)

    by_task: dict[str, list[TrialRecord]] = defaultdict(list)
    for trial in trials:
        by_task[trial.task_key].append(trial)
    tasks = []
    for task_key in sorted(by_task):
        group = by_task[task_key]
        task_values = [
            x.raw_score for x in group if x.state == TrialState.SCORED and _number(x.raw_score)
        ]
        tasks.append(
            {
                "task_key": task_key,
                "planned_trials": len(group),
                "scored_trials": len(task_values),
                "mean": mean(task_values),
                "stddev": sample_stddev(task_values),
                "passed_trials": sum(1 for v in task_values if passed(contract, v))
                if has_pass_rule
                else None,
                # Some planned repetitions have no score: the mean covers fewer samples.
                "partial": 0 < len(task_values) < len(group),
                "excluded_trials": sum(1 for x in group if x.state == TrialState.EXECUTION_ERROR),
                "failure_causes": sorted(
                    {
                        x.failure_cause or "unclassified"
                        for x in group
                        if x.state == TrialState.EXECUTION_ERROR
                    }
                ),
            }
        )
    task_means = [x["mean"] for x in tasks if x["mean"] is not None]
    causes: dict[str, int] = defaultdict(int)
    for trial in trials:
        if trial.state == TrialState.EXECUTION_ERROR:
            causes[trial.failure_cause or "unclassified"] += 1
    attempts = sum(x.attempts for x in trials)
    retried = [x for x in trials if x.attempts > 1]
    if scored and len(scored) == planned:
        completeness = "complete"
    elif scored:
        completeness = "partial"
    else:
        completeness = "none"
    return {
        "contract": contract,
        "planned_trials": planned,
        "scored_trials": len(scored),
        "count_as_failure_trials": count_as_failure,
        "excluded_error_trials": excluded,
        "unfinished_trials": unfinished,
        "active_trials": active,
        "queued_trials": queued,
        "passed_trials": passed_count if has_pass_rule else None,
        "mean": mean(values),
        "stddev": sample_stddev(values),
        "pass_rate": _ratio(passed_count, len(scored) + count_as_failure)
        if has_pass_rule
        else None,
        "scored_coverage": _ratio(len(scored), planned),
        "evaluation_coverage": _ratio(len(scored) + count_as_failure, planned),
        "bench_task_coverage": _ratio(len(by_task), bench_task_count) if bench_task_count else None,
        "bench_score": mean(task_means),
        "bench_scored_tasks": len(task_means),
        "task_count": len(by_task),
        "result_completeness": completeness,
        "excluded_by_cause": dict(sorted(causes.items())),
        "attempts": attempts,
        "retried_trials": len(retried),
        "retry_count": sum(x.attempts - 1 for x in retried),
        "usage": _usage(trials),
        "tasks": tasks,
    }


def compact(summary: dict) -> dict:
    """The run-list subset: enough to read a mean next to its coverage."""
    keys = (
        "planned_trials",
        "scored_trials",
        "excluded_error_trials",
        "unfinished_trials",
        "passed_trials",
        "mean",
        "stddev",
        "pass_rate",
        "scored_coverage",
        "bench_score",
    )
    return {"metric_id": summary["contract"]["metric_id"], **{k: summary[k] for k in keys}}

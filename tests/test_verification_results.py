"""Execution gates reject omissions and non-passes even when a runner exits zero."""

from copy import deepcopy

import pytest

from scripts.verification_results import playwright_result, pytest_result


def execution():
    node = "tests/pages.py::renamed[param]"
    collection = {"nodes": [node], "browser": [node]}
    result = {
        **collection,
        "phases": [
            {"nodeid": node, "when": phase, "outcome": "passed", "xfail": False}
            for phase in ("setup", "call", "teardown")
        ],
        "scripts": {node: ["qa/example-production.mjs"]},
    }
    return collection, result


def test_browser_gate_accepts_renamed_parameterized_nodes():
    collection, result = execution()
    proof = pytest_result(
        collection, result, browser=True, expected_scripts={"qa/example-production.mjs"}
    )
    assert proof["browser_passed"] == collection["browser"]


@pytest.mark.parametrize("defect", ["empty", "missing", "skip", "xfail", "script", "marker"])
def test_browser_gate_rejects_nonexecution(defect):
    collection, result = execution()
    if defect == "empty":
        collection["nodes"] = result["nodes"] = []
    elif defect == "missing":
        result["phases"].pop()
    elif defect == "skip":
        result["phases"][1]["outcome"] = "skipped"
    elif defect == "xfail":
        result["phases"][1]["xfail"] = True
    elif defect == "script":
        result["scripts"] = {}
    else:
        collection["browser"] = []
    with pytest.raises(RuntimeError):
        pytest_result(
            collection, result, browser=True, expected_scripts={"qa/example-production.mjs"}
        )


def ui_report():
    return {
        "suites": [
            {
                "specs": [
                    {
                        "tests": [
                            {
                                "expectedStatus": "passed",
                                "status": "expected",
                                "results": [{"status": "passed"}],
                            }
                        ]
                    }
                ]
            }
        ]
    }


@pytest.mark.parametrize("defect", ["empty", "skip", "unexpected", "missing", "flaky", "error"])
def test_ui_gate_rejects_incomplete_or_skipped_execution(defect):
    report = deepcopy(ui_report())
    test = report["suites"][0]["specs"][0]["tests"][0]
    if defect == "empty":
        report["suites"] = []
    elif defect == "skip":
        test["expectedStatus"] = "skipped"
        test["results"][0]["status"] = "skipped"
    elif defect == "unexpected":
        test["status"] = "unexpected"
    elif defect == "missing":
        test["results"] = []
    elif defect == "flaky":
        test["results"].insert(0, {"status": "failed"})
    else:
        report["errors"] = [{"message": "worker crashed"}]
    with pytest.raises(RuntimeError):
        playwright_result(report)


def test_ui_gate_reads_nested_suites():
    report = {"suites": [ui_report()]}
    assert playwright_result(report)["skipped"] == 0


def test_ui_gate_rejects_missing_collected_node():
    collected = ui_report()
    collected["suites"][0]["specs"].append({"id": "missing", "tests": [{"projectId": "chromium"}]})
    with pytest.raises(RuntimeError, match="node set"):
        playwright_result(ui_report(), collected)

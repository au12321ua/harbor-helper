"""Validate actual execution evidence rather than names or historical test counts."""


def pytest_result(collected, executed, *, browser, expected_scripts):
    nodes = set(collected["nodes"])
    browser_nodes = set(collected["browser"])
    if not nodes or nodes != set(executed["nodes"]):
        raise RuntimeError("pytest collected/executed node set is empty or differs")
    if browser and not browser_nodes:
        raise RuntimeError("browser collection is empty")
    phases = executed["phases"]
    for node in nodes:
        actual = [p for p in phases if p["nodeid"] == node]
        if sorted(p["when"] for p in actual) != ["call", "setup", "teardown"] or any(
            p["outcome"] != "passed" or p["xfail"] for p in actual
        ):
            raise RuntimeError(f"pytest node did not actually pass all phases: {node}")
    scripts = {script for values in executed["scripts"].values() for script in values}
    if browser and scripts != expected_scripts:
        raise RuntimeError(f"production script execution differs: {scripts ^ expected_scripts}")
    if set(executed["scripts"]) - browser_nodes:
        raise RuntimeError("production script executed without browser marker")
    if not browser and (browser_nodes or scripts):
        raise RuntimeError("backend unexpectedly includes browser execution")
    return {
        "cases": len(nodes),
        "skipped": 0,
        "browser_passed": sorted(browser_nodes),
        "production_scripts": sorted(scripts),
    }


def playwright_result(report, collected=None):
    def test_entries(document):
        entries = []

        def visit(suite):
            for spec in suite.get("specs", []):
                entries.extend((spec.get("id"), test) for test in spec["tests"])
            for child in suite.get("suites", []):
                visit(child)

        visit(document)
        return entries

    entries = test_entries(report)
    tests = [test for _, test in entries]
    if collected is not None:
        expected = {(identity, test.get("projectId")) for identity, test in test_entries(collected)}
        actual = {(identity, test.get("projectId")) for identity, test in entries}
        if not expected or expected != actual:
            raise RuntimeError("Playwright collected/executed node set is empty or differs")
    if not tests or report.get("errors"):
        raise RuntimeError("Playwright empty collection or global error")
    for test in tests:
        results = test.get("results", [])
        if (
            test.get("expectedStatus") != "passed"
            or test.get("status") != "expected"
            or not results
            or any(result["status"] != "passed" for result in results)
        ):
            raise RuntimeError("Playwright skipped, failed, flaky or unexecuted test")
    return {"passed": len(tests), "skipped": 0}

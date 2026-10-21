"""Machine-readable collection and phase outcomes for the shared verification gate.

Loaded explicitly by verify.py, so ordinary pytest does not create evidence files.
"""

import json
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption(
        "--gate-report", type=Path, help="write verification collection/phase evidence"
    )


class Outcomes:
    def __init__(self):
        self.phases = []

    def pytest_runtest_logreport(self, report):
        self.phases.append(
            {
                "nodeid": report.nodeid,
                "when": report.when,
                "outcome": report.outcome,
                "xfail": hasattr(report, "wasxfail"),
            }
        )


def pytest_sessionstart(session):
    session.config.pluginmanager.register(Outcomes(), "gate-outcomes")


def pytest_sessionfinish(session, exitstatus):
    target = session.config.getoption("--gate-report")
    if target:
        plugin = session.config.pluginmanager.get_plugin("gate-outcomes")
        target.write_text(
            json.dumps(
                {
                    "exit": int(exitstatus),
                    "nodes": [item.nodeid for item in session.items],
                    "browser": [
                        item.nodeid
                        for item in session.items
                        if item.get_closest_marker("browser") is not None
                    ],
                    "phases": plugin.phases,
                    "scripts": {
                        item.nodeid: [v for k, v in item.user_properties if k == "browser_script"]
                        for item in session.items
                        if any(k == "browser_script" for k, _ in item.user_properties)
                    },
                },
                indent=2,
            )
            + "\n"
        )

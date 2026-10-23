"""The service never loads Harbor (15 section 11.1); the Runner owns that dependency."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_service_imports_do_not_load_harbor():
    code = (
        "import sys\n"
        "import maestro.cli, maestro.application, maestro.api.app\n"
        "import maestro.execution.harbor, maestro.services.worker\n"
        "loaded = sorted(m for m in sys.modules if m == 'harbor' or m.startswith('harbor.'))\n"
        "print(loaded)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "[]"


def test_service_dependencies_exclude_harbor():
    text = (ROOT / "pyproject.toml").read_text()
    assert '"harbor' not in text
    runner = (ROOT / "runner" / "pyproject.toml").read_text()
    assert '"harbor==0.24.0"' in runner  # exact pin, upgraded deliberately with the mapping


def test_service_and_runner_agree_on_harness_adapters():
    """The executor declares the Runner's adapters; the two live in different environments."""
    import json
    import os

    import pytest

    from maestro.execution.harbor import HarborExecutor

    runner = Path(os.environ.get("MAESTRO_RUNNER_PYTHON", ROOT / "runner/.venv/bin/python"))
    if not runner.exists():
        pytest.skip("Runner environment not installed")
    code = (
        "import json; from maestro_runner.agents import ADAPTERS\n"
        "print(json.dumps({k: [sorted(v['protocols']), sorted(v['parameters'])]"
        " for k, v in ADAPTERS.items()}))\n"
    )
    result = subprocess.run([str(runner), "-c", code], capture_output=True, text=True, check=True)
    declared = {
        name: [sorted(protocols), sorted(HarborExecutor.harness_parameters[name])]
        for name, protocols in HarborExecutor.harness_adapters.items()
    }
    assert json.loads(result.stdout) == declared

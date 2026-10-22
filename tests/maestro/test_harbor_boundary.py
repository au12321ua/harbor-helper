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

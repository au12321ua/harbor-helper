"""Repository anchors shared by test suites regardless of their directory depth."""

from pathlib import Path

REPO = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "pyproject.toml").is_file() and (parent / "src/harbor_helper").is_dir()
)
FIXTURES = REPO / "tests/fixtures"

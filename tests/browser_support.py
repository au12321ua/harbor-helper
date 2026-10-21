"""Execute production-page probes and record success only after Node exits cleanly."""

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run_browser(request, script, *, env, timeout=60):
    assert request.node.get_closest_marker("browser") is not None, "probe requires browser marker"
    script = Path(script)
    result = subprocess.run(
        ["node", str(script)], env=env, text=True, capture_output=True, check=False, timeout=timeout
    )
    assert result.returncode == 0, result.stdout + result.stderr
    request.node.user_properties.append(("browser_script", script.relative_to(REPO).as_posix()))
    return result

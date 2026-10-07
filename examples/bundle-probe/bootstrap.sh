#!/bin/sh
set -eu
/opt/cad-venv/bin/python - <<'PY'
import json
import helper_probe
from pathlib import Path
print('SDK_EXECUTED=' + helper_probe.VERSION)
config = json.loads(Path('/opt/harbor-helper-bundle/config/opencode.json').read_text())
print('CONFIG_USED=' + config['instructions'][0])
skill = Path('/skills/helper-probe/SKILL.md')
assert 'bundle-probe-v1' in skill.read_text()
print('NATIVE_SKILL_INJECTED=' + str(skill))
PY

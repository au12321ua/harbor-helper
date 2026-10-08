#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
python - <<'CHECK'
from pathlib import Path

answer = Path('/app/answer.txt')
reward = int(answer.is_file() and answer.read_bytes() == b'dataset-switch-ok\n')
Path('/logs/verifier/reward.txt').write_text(f'{reward}\n')
CHECK

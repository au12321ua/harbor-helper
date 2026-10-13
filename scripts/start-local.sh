#!/usr/bin/env bash
set -euo pipefail
if [[ $(uname -s) != Linux ]]; then
  echo 'Local startup requires Linux.' >&2
  exit 1
fi
if ! command -v python3 >/dev/null; then
  echo 'Install Python 3.12–3.13 and uv first.' >&2
  exit 1
fi
exec python3 "$(dirname "$(readlink -f "$0")")/local_platform.py" "$@"

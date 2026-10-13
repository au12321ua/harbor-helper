import importlib.metadata, json, pathlib, sys
from harbor_helper.cli import main
module=pathlib.Path(__import__("harbor_helper").__file__).resolve()
assert str(module).startswith("/tmp/hh-checker-independent-2e5a71-20261012/wheel-root/")
assert importlib.metadata.version("harbor-helper")=="0.2.0"
sys.argv=["harbor-helper", "--help"]
main()

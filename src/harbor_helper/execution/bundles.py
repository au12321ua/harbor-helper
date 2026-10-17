"""Shared experiment bundle validation, independent of job submission."""

from harbor_helper.execution.config import reject_secrets
from harbor_helper.persistence.files import read_json, tree_digest


def check_bundle(path, access_value=None):
    from harbor_helper.security.access_tokens import check_access_tree

    check_access_tree(path, access_value)
    allowed = {"skills", "sdk", "config", "bootstrap.sh"}
    if {p.name for p in path.iterdir()} - allowed:
        raise ValueError("Bundle supports skills/, sdk/, config/opencode.json, bootstrap.sh")
    tree_digest(path)
    config_dir = path / "config"
    if config_dir.exists() and {p.name for p in config_dir.iterdir()} - {"opencode.json"}:
        raise ValueError("Bundle config supports opencode.json only")
    cfg = config_dir / "opencode.json"
    if cfg.exists():
        from harbor_helper.execution.model_protocols import bundle_config

        reject_secrets(bundle_config(read_json(cfg)))
    for p in path.rglob("*"):
        if p.is_file() and (
            p.name.startswith(".env")
            or any(s in p.name.lower() for s in ("secret", "credential", ".pem"))
        ):
            raise ValueError("Credential files cannot be bundled")

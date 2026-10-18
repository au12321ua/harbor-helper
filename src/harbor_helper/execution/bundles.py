"""Shared experiment bundle validation, independent of job submission."""

from harbor_helper.execution.config import reject_secrets
from harbor_helper.persistence.files import read_json, tree_digest


class BundleLayoutError(ValueError):
    """A safe, fixed explanation of an unsupported bundle directory layout."""


def check_bundle(path, access_value=None):
    from harbor_helper.security.access_tokens import check_access_tree

    check_access_tree(path, access_value)
    allowed = {"skills", "sdk", "config", "bootstrap.sh"}
    if {p.name for p in path.iterdir()} - allowed:
        raise BundleLayoutError(
            "附件 ZIP 根目录仅支持 skills/、sdk/、config/opencode.json 和 bootstrap.sh；"
            "请直接压缩这些内容，去掉外层目录。"
        )
    tree_digest(path)
    config_dir = path / "config"
    if config_dir.exists() and {p.name for p in config_dir.iterdir()} - {"opencode.json"}:
        raise BundleLayoutError("附件 ZIP 的 config/ 目录仅支持 opencode.json。")
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

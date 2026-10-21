"""Ops behavior against isolated production HTTP/scheduler and synthetic executions."""

import argparse
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ops = module("ops")
verify = module("verify")
SHA = "a" * 40


def close_stores(p):
    p.data.store.close()
    p.app.store.close()


def reopen_store(p):
    from harbor_helper.persistence.store import Store

    p.data.store = Store(p.data.root)


def backup_args(base, out, kind="online"):
    return argparse.Namespace(directory=base, output=out, kind=kind, release=SHA, lock_timeout=0.1)


def restore_args(result, target):
    snapshot = Path(result["snapshot"])
    return argparse.Namespace(
        snapshot=snapshot,
        target=target,
        release=SHA,
        master_file=snapshot.with_name(snapshot.name + ".master"),
    )

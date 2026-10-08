"""Preinstall fixed OpenCode over a recorded CAD image, without credentials/model calls."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.18.35"


def command(argv, **kwargs):
    # The build never receives provider credentials, even if the caller has them.
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        in {
            "PATH",
            "HOME",
            "DOCKER_HOST",
            "DOCKER_CONTEXT",
            "LANG",
            "TMPDIR",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "NO_PROXY",
            "http_proxy",
            "https_proxy",
            "no_proxy",
        }
    }
    return subprocess.run(argv, check=True, env=env, **kwargs)


def inspect(image):
    return json.loads(
        command(["docker", "image", "inspect", image], capture_output=True, text=True).stdout
    )[0]


def build_identity(base_id, version, dockerfile):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("A fixed numeric opencode version is required")
    return hashlib.sha256(base_id.encode() + version.encode() + dockerfile).hexdigest()


def inventory(image):
    probe = r"""
import hashlib, importlib.util, importlib.metadata, json, subprocess
from pathlib import Path
installed = Path(next(iter(importlib.util.find_spec('simplecadapi').submodule_search_locations)))
hashes = {}
for label, root in [('source', Path('/opt/simplecadapi')),
                    ('skill', Path('/skills/simplecadapi')), ('installed', installed)]:
    for file in sorted(root.rglob('*')):
        if file.is_file() and '__pycache__' not in file.parts:
            hashes[label + '/' + str(file.relative_to(root))] = hashlib.sha256(file.read_bytes()).hexdigest()
freeze = subprocess.run(['python', '-m', 'pip', 'freeze', '--all'], check=True,
                        capture_output=True, text=True).stdout
print(json.dumps({'cadir_version': importlib.metadata.version('simplecadapi'),
                  'hashes': hashes, 'pip_freeze': freeze}))
"""
    return json.loads(
        command(
            ["docker", "run", "--rm", "--network", "none", image, "python", "-c", probe],
            capture_output=True,
            text=True,
        ).stdout
    )


def validate(image, base, expected_inventory, digest, version):
    current = inspect(image)
    layers = base["RootFS"]["Layers"]
    if current["RootFS"]["Layers"][: len(layers)] != layers:
        raise ValueError("Preinstalled image does not inherit the recorded base layers")
    labels = current["Config"].get("Labels") or {}
    if labels.get("org.harbor-helper.opencode-inputs") != digest:
        raise ValueError("Preinstalled image build inputs differ")
    actual_inventory = inventory(current["Id"])
    if actual_inventory != expected_inventory:
        raise ValueError("CAD SDK/source/skill/Python dependencies changed in derived image")
    probe = command(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            current["Id"],
            "bash",
            "-lc",
            "opencode --version && node --version && npm --version",
        ],
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if not probe or probe[0] != version:
        raise ValueError("Preinstalled OpenCode actual version differs")
    return current["Id"], {"opencode": probe[0], "node": probe[1], "npm": probe[2]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-image", default="harbor-helper/cad-runtime:aa0d35429b998a7109e7")
    parser.add_argument("--opencode-version", default=VERSION)
    parser.add_argument("--output", type=Path, default=ROOT / ".state/opencode-runtime-build")
    parser.add_argument("--reuse-image", help="Validate existing build inputs/layers/files/version")
    args = parser.parse_args()
    os.umask(0o077)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    base = inspect(args.base_image)
    dockerfile = (ROOT / "images/opencode-runtime/Dockerfile").read_bytes()
    digest = build_identity(base["Id"], args.opencode_version, dockerfile)
    image = "harbor-helper/cad-opencode:" + digest[:20]
    base_alias = "harbor-helper/opencode-base:" + base["Id"].removeprefix("sha256:")
    command(["docker", "tag", base["Id"], base_alias])
    base_inventory = inventory(base["Id"])
    if base_inventory["cadir_version"] != "2.1.4" or not base_inventory["hashes"]:
        raise ValueError("Expected the fixed CADIR 2.1.4 runtime with matching source and skill")
    (output / "cad-inventory.json").write_text(json.dumps(base_inventory, indent=2) + "\n")
    inputs = {
        "base_image_id": base["Id"],
        "base_reference": args.base_image,
        "opencode_version": args.opencode_version,
        "image": image,
        "dockerfile_sha256": hashlib.sha256(dockerfile).hexdigest(),
        "build_inputs_sha256": digest,
        "model_requests": 0,
        "credentials_used": False,
        "transitive_dependencies": "APT/npm resolved at build; runtime versions recorded",
    }
    (output / "inputs.json").write_text(json.dumps(inputs, indent=2) + "\n")
    started = time.monotonic()
    if args.reuse_image:
        image_id, versions = validate(
            args.reuse_image, base, base_inventory, digest, args.opencode_version
        )
        command(["docker", "tag", image_id, image])
    else:
        with tempfile.TemporaryDirectory(prefix="opencode-build-", dir=output) as tmp:
            context = Path(tmp)
            (context / "Dockerfile").write_bytes(dockerfile)
            argv = [
                "docker",
                "build",
                "--build-arg",
                "BASE_IMAGE=" + base_alias,
                "--build-arg",
                "OPENCODE_VERSION=" + args.opencode_version,
                "--label",
                "org.harbor-helper.opencode-inputs=" + digest,
                "--label",
                "org.harbor-helper.base-image-id=" + base["Id"],
                "-t",
                image,
                str(context),
            ]
            (output / "build-command.json").write_text(json.dumps(argv, indent=2) + "\n")
            with (output / "build.log").open("w") as log:
                command(argv, stdout=log, stderr=log)
        image_id, versions = validate(image, base, base_inventory, digest, args.opencode_version)
    value = {
        **inputs,
        "image_id": image_id,
        "runtime_versions": versions,
        "cad_inventory_unchanged": True,
        "checked_cad_files": len(base_inventory["hashes"]),
        "reused_image": args.reuse_image,
        "maintenance_seconds": time.monotonic() - started,
    }
    (output / "provenance.json").write_text(json.dumps(value, indent=2) + "\n")
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()

"""Export pinned CADIR committed source/skill and build a local runtime, without publishing."""

import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import tempfile
import tomllib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = (
    "pyproject.toml",
    "README.md",
    "LICENSE",
    "MANIFEST.in",
    "skillproj.toml",
    "src",
    "docs",
)


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def extract_snapshot(archive, destination):
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        members = source.getmembers()
        for member in members:
            name = PurePosixPath(member.name)
            if (
                name.is_absolute()
                or ".." in name.parts
                or not name.parts
                or name.parts[0] not in ALLOWLIST
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("Unsafe runtime source archive entry: " + member.name)
        files = {m.name for m in members if m.isfile()}
        if not {"pyproject.toml", "README.md", "LICENSE", "docs/skill/SKILL.md"} <= files:
            raise ValueError("Missing wheel metadata or matching CADIR skill")
        source.extractall(destination, members=members, filter="data")


def prepare(repo, destination):
    cfg = json.loads((ROOT / "configs/cad-runtime.json").read_text())
    commit = git(repo, "rev-parse", "--verify", cfg["cadir_commit"] + "^{commit}").decode().strip()
    if commit != cfg["cadir_commit"]:
        raise ValueError("Fixed CADIR commit not available")
    metadata = tomllib.loads(git(repo, "show", commit + ":pyproject.toml").decode())
    if (
        metadata["project"]["name"] != "simplecadapi"
        or metadata["project"]["version"] != cfg["cadir_version"]
    ):
        raise ValueError("Source version differs from runtime pin")
    archive = git(repo, "archive", "--format=tar", commit, "--", *ALLOWLIST)
    dockerfile = (ROOT / "images/cad-runtime/Dockerfile").read_bytes()
    digest = hashlib.sha256(archive + dockerfile + cfg["base_image"].encode()).hexdigest()
    image = cfg["image_name"] + ":" + digest[:20]
    destination.mkdir(parents=True, exist_ok=False)
    extract_snapshot(archive, destination / "cadir")
    (destination / "Dockerfile").write_bytes(dockerfile)
    return {
        **cfg,
        "image": image,
        "source_archive_sha256": hashlib.sha256(archive).hexdigest(),
        "dockerfile_sha256": hashlib.sha256(dockerfile).hexdigest(),
        "build_inputs_sha256": digest,
        "matching_skill": "docs/skill",
        "context": str(destination),
        "transitive_dependencies": "resolved at build; pip freeze recorded",
    }


def validate_reuse(image, manifest_path, context, expected):
    """Compare build inputs and the actual installed source/skill, not only a tag."""
    evidence = json.loads(manifest_path.read_text())
    fields = {
        "cadir_commit": "cadir_commit",
        "version": "cadir_version",
        "archive_sha256": "source_archive_sha256",
        "dockerfile_sha256": "dockerfile_sha256",
        "base": "base_image",
    }
    if any(evidence.get(k) != expected[v] for k, v in fields.items()):
        raise ValueError("Reused build inputs differ from the pinned runtime")
    hashes = {
        p.relative_to(context / "cadir").as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (context / "cadir").rglob("*")
        if p.is_file()
    }
    probe = r"""
import hashlib, importlib.metadata, importlib.util, json, sys
from pathlib import Path
payload = json.load(sys.stdin)
installed = Path(next(iter(importlib.util.find_spec('simplecadapi').submodule_search_locations)))
errors = []
for name, digest in payload['hashes'].items():
    paths = [Path('/opt/simplecadapi') / name]
    if name.startswith('docs/skill/'):
        paths.append(Path('/skills/simplecadapi') / name.removeprefix('docs/skill/'))
    if name.startswith('src/simplecadapi/') and name.endswith('.py'):
        paths.append(installed / name.removeprefix('src/simplecadapi/'))
    for path in paths:
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            errors.append(str(path))
if importlib.metadata.version('simplecadapi') != payload['version']:
    errors.append('installed version')
print(json.dumps({'verified': not errors, 'errors': errors, 'checked_source_files': len(payload['hashes'])}))
sys.exit(bool(errors))
"""
    result = subprocess.run(
        ["docker", "run", "--rm", "-i", "--network", "none", image, "python", "-c", probe],
        input=json.dumps({"hashes": hashes, "version": expected["cadir_version"]}),
        check=True,
        text=True,
        capture_output=True,
    )
    expected["reuse_validation"] = json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cadir", required=True, type=Path, help="Read-only CADIR git checkout")
    parser.add_argument("--output", type=Path, default=ROOT / ".state/runtime-build")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--reuse-image", help="Reuse an independently validated local runtime")
    parser.add_argument(
        "--reuse-manifest", type=Path, help="Evidence manifest for the reused build"
    )
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="context-", dir=output) as tmp:
        context = Path(tmp) / "build"
        provenance = prepare(args.cadir.expanduser().resolve(), context)
        if args.reuse_image:
            if args.prepare_only or not args.reuse_manifest:
                parser.error(
                    "--reuse-image requires --reuse-manifest and cannot use --prepare-only"
                )
            validate_reuse(args.reuse_image, args.reuse_manifest, context, provenance)
            subprocess.run(["docker", "tag", args.reuse_image, provenance["image"]], check=True)
            provenance["reused_image"] = args.reuse_image
        elif not args.prepare_only:
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--build-arg",
                    "BASE_IMAGE=" + provenance["base_image"],
                    "--label",
                    "org.harbor-helper.cadir-commit=" + provenance["cadir_commit"],
                    "--label",
                    "org.harbor-helper.build-inputs=" + provenance["build_inputs_sha256"],
                    "-t",
                    provenance["image"],
                    str(context),
                ],
                check=True,
            )
        if not args.prepare_only:
            result = subprocess.run(
                ["docker", "image", "inspect", provenance["image"], "--format", "{{.Id}}"],
                check=True,
                text=True,
                capture_output=True,
            )
            provenance["image_id"] = result.stdout.strip()
            freeze = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    provenance["image"],
                    "cat",
                    "/opt/cad-runtime-pip-freeze.txt",
                ],
                check=True,
                text=True,
                capture_output=True,
            )
            (output / "pip-freeze.txt").write_text(freeze.stdout)
        provenance.pop("context")  # Temporary context is intentionally removed.
        (output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
        print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    main()

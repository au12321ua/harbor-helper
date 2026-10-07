import importlib.util
import io
import tarfile
from pathlib import Path

import pytest

script = Path(__file__).resolve().parents[1] / "scripts" / "build_cad_runtime.py"
spec = importlib.util.spec_from_file_location("runtime_build", script)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def archive(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for name, kind in entries:
            info = tarfile.TarInfo(name)
            if kind == "link":
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            else:
                content = b"committed source"
                info.size = len(content)
                tar.addfile(info, io.BytesIO(content))
    return output.getvalue()


@pytest.mark.parametrize(
    "name,kind",
    [
        ("../escape", "file"),
        ("/etc/escape", "file"),
        ("docs/link", "link"),
        ("secrets/key", "file"),
    ],
)
def test_runtime_archive_rejects_unsafe_inputs_before_writes(tmp_path, name, kind):
    with pytest.raises(ValueError, match="Unsafe"):
        build.extract_snapshot(archive([(name, kind)]), tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_runtime_archive_requires_matching_skill(tmp_path):
    with pytest.raises(ValueError, match="matching CADIR skill"):
        build.extract_snapshot(archive([("pyproject.toml", "file")]), tmp_path / "out")


def test_runtime_archive_exports_only_validated_committed_tree(tmp_path):
    names = ["pyproject.toml", "README.md", "LICENSE", "docs/skill/SKILL.md", "src/api.py"]
    build.extract_snapshot(archive([(name, "file") for name in names]), tmp_path / "out")
    assert (tmp_path / "out" / "docs/skill/SKILL.md").read_text() == "committed source"
    assert not (tmp_path / "out" / "secrets").exists()

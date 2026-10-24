"""Fail when a tracked Markdown file links to a repository path that does not exist.

    python tools/check_doc_links.py

Only relative links are checked; web links, mail links and pure anchors are skipped.
Ignored paths such as ``.local/`` are not part of the repository, so a link into them
is reported too: public documents must not point at private evidence.
"""

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^(```|~~~)")


def tracked() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return out.splitlines()


def links(text: str):
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if FENCE.match(line.strip()):
            fenced = not fenced
            continue
        if fenced:
            continue
        line = re.sub(r"`[^`]*`", "", line)
        for match in LINK.finditer(line):
            yield number, match.group(1)


def broken(path: Path, files: set[str]) -> list[str]:
    problems = []
    for number, target in links(path.read_text(encoding="utf-8")):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("#"):
            continue
        relative = unquote(target.split("#", 1)[0])
        resolved = (path.parent / relative).resolve()
        try:
            key = resolved.relative_to(ROOT).as_posix()
        except ValueError:
            problems.append(f"{path.relative_to(ROOT)}:{number}: {target} leaves the repository")
            continue
        if key not in files and not any(f.startswith(key + "/") for f in files):
            problems.append(f"{path.relative_to(ROOT)}:{number}: {target} does not exist")
    return problems


def main() -> int:
    files = set(tracked())
    markdown = [ROOT / f for f in sorted(files) if f.endswith(".md")]
    problems = [p for path in markdown for p in broken(path, files)]
    for problem in problems:
        print(problem, file=sys.stderr)
    print(f"{len(problems)} broken link(s)" if problems else "All Markdown links resolve.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Dataset source boundary: search, versions, tasks and content of a fixed version."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SourceTask:
    task_key: str
    content_digest: str
    definition: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SourceVersion:
    namespace: str
    name: str
    upstream_ref: str
    ref_kind: str  # tag | revision | digest
    resolved_digest: str
    tasks: tuple[SourceTask, ...]
    description: str = ""


class DatasetSource(Protocol):
    kind: str

    def search(self, query: str) -> list[dict]: ...

    def resolve(self, namespace: str, name: str, ref: str) -> SourceVersion:
        """Resolve a tag/revision/digest to an immutable content digest."""
        ...

    def fetch(self, version: SourceVersion, destination: Path) -> str:
        """Materialize the exact content; returns the local materialization digest."""
        ...

import fnmatch
from typing import cast

from harbor.models.task.id import PackageTaskId
from harbor.registry.client.package import PackageDatasetClient
from harbor.tasks.client import TaskClient

from harbor_helper.persistence.files import tree_digest


class UnsupportedDatasetError(ValueError):
    """A source feature is outside this service's supported execution contract."""


class TaskSelectionError(ValueError):
    """Exact requested task names or immutable refs disagree with the catalog."""


def exact_task_names(names, known_names):
    """Validate every requested name, then deduplicate in first-occurrence order."""
    if not isinstance(names, list) or not names:
        raise TaskSelectionError("Select a nonempty list of exact catalog task names")
    if any(not isinstance(name, str) or not name or name not in known_names for name in names):
        raise TaskSelectionError("Selected task name is invalid or absent from the catalog")
    return list(dict.fromkeys(names))


async def resolve_dataset(reference, target, task_filter=None, *, selected_tasks=None):
    client = PackageDatasetClient()
    metadata = await client.get_dataset_metadata(reference)
    if not cast(str, metadata.version).startswith("sha256:"):
        raise ValueError("Dataset did not resolve to immutable digest")
    if metadata.metrics or metadata.files:
        raise UnsupportedDatasetError("Dataset-level custom metrics/files are not supported")
    tasks = cast(list[PackageTaskId], metadata.task_ids)
    if selected_tasks is not None:
        catalog = {t.name: t for t in tasks}
        if not isinstance(selected_tasks, list) or any(
            not isinstance(entry, dict) for entry in selected_tasks
        ):
            raise TaskSelectionError("Select exact catalog task records")
        names = exact_task_names([entry.get("name") for entry in selected_tasks], catalog)
        # Check every record before deduplication: a repeated name cannot conceal
        # an invalid package or immutable ref supplied later in the request.
        for entry in selected_tasks:
            task = catalog[entry["name"]]
            if task.ref != entry.get("ref") or task.get_name() != entry.get("package"):
                raise TaskSelectionError("Selected task differs from verified catalog")
        tasks = [catalog[name] for name in sorted(names)]
    elif task_filter:
        tasks = [
            t
            for t in tasks
            if fnmatch.fnmatch(t.get_name(), task_filter) or fnmatch.fnmatch(t.name, task_filter)
        ]
    if not tasks:
        raise ValueError("No accessible tasks match the dataset/filter")
    identities = []
    target.mkdir()
    for task in tasks:
        if not task.ref or not task.ref.startswith("sha256:"):
            raise ValueError("Task source not fixed")
        result = (
            await TaskClient().download_tasks(
                [task], overwrite=False, output_dir=target, export=True
            )
        ).results[0]
        destination = target / task.name
        if result.content_hash != task.ref.removeprefix("sha256:"):
            raise ValueError("Downloaded task hash differs from fixed source")
        identities.append(
            {
                "package": task.get_name(),
                "ref": task.ref,
                "directory": task.name,
                "snapshot_digest": tree_digest(destination),
            }
        )
    return {
        "requested": reference,
        "resolved": metadata.name + "@" + cast(str, metadata.version),
        "tasks": identities,
    }


def verify_inputs(run_dir, manifest):
    if (run_dir / "bundle").exists():
        from harbor_helper.security.access_tokens import check_access_tree

        check_access_tree(run_dir / "bundle")
    for task in manifest["source"]["tasks"]:
        p = run_dir / "tasks" / task["directory"]
        if not p.is_dir() or tree_digest(p) != task["snapshot_digest"]:
            raise ValueError("Fixed task snapshot unavailable or changed; submit a new experiment")
    if manifest["bundle_digest"] and tree_digest(run_dir / "bundle") != manifest["bundle_digest"]:
        raise ValueError("Fixed bundle snapshot unavailable or changed")

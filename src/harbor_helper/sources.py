import fnmatch

from harbor.registry.client.package import PackageDatasetClient
from harbor.tasks.client import TaskClient

from harbor_helper.storage import tree_digest


async def resolve_dataset(reference, target, task_filter=None):
    client = PackageDatasetClient()
    metadata = await client.get_dataset_metadata(reference)
    if not metadata.version.startswith("sha256:"):
        raise ValueError("Dataset did not resolve to immutable digest")
    if metadata.metrics or metadata.files:
        raise ValueError("Dataset-level custom metrics/files are not supported in v0")
    tasks = metadata.task_ids
    if task_filter:
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
        "resolved": metadata.name + "@" + metadata.version,
        "tasks": identities,
    }


def verify_inputs(run_dir, manifest):
    for task in manifest["source"]["tasks"]:
        p = run_dir / "tasks" / task["directory"]
        if not p.is_dir() or tree_digest(p) != task["snapshot_digest"]:
            raise ValueError("Fixed task snapshot unavailable or changed; submit a new experiment")
    if manifest["bundle_digest"] and tree_digest(run_dir / "bundle") != manifest["bundle_digest"]:
        raise ValueError("Fixed bundle snapshot unavailable or changed")

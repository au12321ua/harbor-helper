"""Service container: one place that wires settings, database, boundaries and services."""

from dataclasses import dataclass

from maestro.boundaries.dataset_source import DatasetSource
from maestro.boundaries.environment import Environment
from maestro.boundaries.executor import Executor
from maestro.boundaries.storage import ArtifactStore, LocalArtifactStore
from maestro.config import Settings
from maestro.db import migrate
from maestro.db.engine import Database
from maestro.execution.materials import TaskMaterials
from maestro.security.master_key import MasterKeys
from maestro.services.accounts import Accounts
from maestro.services.artifacts import Artifacts
from maestro.services.capacity import Capacity, HostCapacity
from maestro.services.catalog import Catalog
from maestro.services.credentials import Credentials
from maestro.services.datasets import Datasets
from maestro.services.disk import DiskWatch
from maestro.services.exports import Exports
from maestro.services.maintenance import Maintenance
from maestro.services.operations import Operations
from maestro.services.pats import Pats
from maestro.services.preparation import Preparer
from maestro.services.recycle import Recycle
from maestro.services.runs import Runs
from maestro.services.worker import Worker


@dataclass
class Maestro:
    settings: Settings
    db: Database
    keys: MasterKeys
    accounts: Accounts
    pats: Pats
    credentials: Credentials
    operations: Operations
    catalog: Catalog
    datasets: Datasets
    runs: Runs
    artifacts: Artifacts
    exports: Exports
    recycle: Recycle
    maintenance: Maintenance
    disk: DiskWatch
    capacity: Capacity
    store: ArtifactStore
    executor: Executor | None
    worker: Worker | None
    preparer: Preparer | None

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        executor: Executor | None = None,
        store: ArtifactStore | None = None,
        db: Database | None = None,
        environment: Environment | None = None,
        sources: dict[str, DatasetSource] | None = None,
    ) -> "Maestro":
        """The worker runs only with an executor; preparation also needs an environment."""
        db = db or Database.open(settings.database)
        store = store or LocalArtifactStore(settings.artifacts_dir)
        keys = MasterKeys(db, settings.master_key_dir, settings.data_dir)
        credentials = Credentials(db, keys)
        sources = sources or {}
        host = HostCapacity.detect(
            settings.worker_slots, settings.execution_cpus, settings.execution_memory_mb
        )
        disk = DiskWatch(settings.data_dir, settings)
        materials = TaskMaterials(settings.cache_dir)
        preparer = (
            Preparer(db, environment, sources, materials, credentials)
            if environment is not None
            else None
        )
        worker = (
            Worker(db, executor, store, host, disk=disk, preparer=preparer)
            if executor is not None
            else None
        )
        location = environment.location_id if environment is not None else "local-docker"
        runs = Runs(db, host, disk)
        artifacts = Artifacts(db, store)
        exports = Exports(db, store, settings.exports_dir, runs, disk)
        return cls(
            settings=settings,
            db=db,
            keys=keys,
            accounts=Accounts(db, settings.setup_token_file, settings.session_hours),
            pats=Pats(db),
            credentials=credentials,
            operations=Operations(db),
            catalog=Catalog(db, location),
            datasets=Datasets(db, sources, credentials),
            runs=runs,
            artifacts=artifacts,
            exports=exports,
            recycle=Recycle(db, store, materials, exports, environment),
            maintenance=Maintenance(artifacts, exports),
            disk=disk,
            capacity=Capacity(db, host),
            store=store,
            executor=executor,
            worker=worker,
            preparer=preparer,
        )

    def schema_state(self) -> dict:
        current = migrate.current(self.db)
        head = migrate.head()
        return {"current": current, "head": head, "compatible": current == head}

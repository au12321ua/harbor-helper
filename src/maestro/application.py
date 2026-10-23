"""Service container: one place that wires settings, database, boundaries and services."""

from dataclasses import dataclass

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
from maestro.services.disk import DiskWatch
from maestro.services.exports import Exports
from maestro.services.maintenance import Maintenance
from maestro.services.operations import Operations
from maestro.services.pats import Pats
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

    @classmethod
    def build(
        cls,
        settings: Settings,
        *,
        executor: Executor | None = None,
        store: ArtifactStore | None = None,
        db: Database | None = None,
    ) -> "Maestro":
        db = db or Database.open(settings.database)
        store = store or LocalArtifactStore(settings.artifacts_dir)
        keys = MasterKeys(db, settings.master_key_dir, settings.data_dir)
        host = HostCapacity.detect(
            settings.worker_slots, settings.execution_cpus, settings.execution_memory_mb
        )
        disk = DiskWatch(settings.data_dir, settings)
        worker = Worker(db, executor, store, host, disk=disk) if executor is not None else None
        runs = Runs(db, host, disk)
        artifacts = Artifacts(db, store)
        exports = Exports(db, store, settings.exports_dir, runs)
        return cls(
            settings=settings,
            db=db,
            keys=keys,
            accounts=Accounts(db, settings.setup_token_file, settings.session_hours),
            pats=Pats(db),
            credentials=Credentials(db, keys),
            operations=Operations(db),
            catalog=Catalog(db),
            runs=runs,
            artifacts=artifacts,
            exports=exports,
            recycle=Recycle(db, store, TaskMaterials(settings.cache_dir), exports),
            maintenance=Maintenance(artifacts, exports),
            disk=disk,
            capacity=Capacity(db, host),
            store=store,
            executor=executor,
            worker=worker,
        )

    def schema_state(self) -> dict:
        current = migrate.current(self.db)
        head = migrate.head()
        return {"current": current, "head": head, "compatible": current == head}

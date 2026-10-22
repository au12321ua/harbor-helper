"""Service container: one place that wires settings, database, boundaries and services."""

from dataclasses import dataclass

from maestro.boundaries.executor import Executor
from maestro.boundaries.storage import ArtifactStore, LocalArtifactStore
from maestro.config import Settings
from maestro.db import migrate
from maestro.db.engine import Database
from maestro.security.master_key import MasterKeys
from maestro.services.accounts import Accounts
from maestro.services.artifacts import Artifacts
from maestro.services.catalog import Catalog
from maestro.services.credentials import Credentials
from maestro.services.operations import Operations
from maestro.services.pats import Pats
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
        worker = (
            Worker(db, executor, store, slots=max(1, settings.worker_slots))
            if executor is not None
            else None
        )
        return cls(
            settings=settings,
            db=db,
            keys=keys,
            accounts=Accounts(db, settings.setup_token_file, settings.session_hours),
            pats=Pats(db),
            credentials=Credentials(db, keys),
            operations=Operations(db),
            catalog=Catalog(db),
            runs=Runs(db),
            artifacts=Artifacts(db, store),
            store=store,
            executor=executor,
            worker=worker,
        )

    def schema_state(self) -> dict:
        current = migrate.current(self.db)
        head = migrate.head()
        return {"current": current, "head": head, "compatible": current == head}

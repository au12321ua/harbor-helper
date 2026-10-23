"""Background upkeep that runs with or without an executor: export builds, artifact
retention and export expiry (07 sections 6 and 7), plus start-up reconciliation."""

import asyncio
import logging

from maestro.services.artifacts import Artifacts
from maestro.services.exports import Exports

log = logging.getLogger(__name__)
SWEEP_SECONDS = 60.0


class Maintenance:
    def __init__(
        self,
        artifacts: Artifacts,
        exports: Exports,
        *,
        poll_seconds: float = 1.0,
        sweep_seconds: float = SWEEP_SECONDS,
    ):
        self.artifacts = artifacts
        self.exports = exports
        self.poll_seconds = poll_seconds
        self.sweep_seconds = sweep_seconds
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping = False

    def start(self) -> dict:
        """Before any run executes: index/file reconciliation and interrupted exports."""
        report = {
            "storage": self.artifacts.reconcile(),
            "exports_requeued": self.exports.recover(),
        }
        return report

    def run_once(self) -> dict:
        """Build every queued export, then reclaim what has expired."""
        built = 0
        while (export_id := self.exports.next_queued()) is not None:
            self.exports.build(export_id)
            built += 1
        return {
            "exports_built": built,
            "artifacts": self.artifacts.sweep(),
            "exports_expired": self.exports.expire(),
        }

    def wake(self) -> None:
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._wake.set)

    async def run_forever(self) -> None:
        self._loop = asyncio.get_running_loop()
        last_sweep = float("-inf")
        while not self._stopping:
            try:
                while (export_id := self.exports.next_queued()) is not None:
                    await asyncio.to_thread(self.exports.build, export_id)
                if self._loop.time() - last_sweep >= self.sweep_seconds:
                    last_sweep = self._loop.time()
                    await asyncio.to_thread(self.artifacts.sweep)
                    await asyncio.to_thread(self.exports.expire)
            except Exception:
                log.exception("maintenance pass failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self.poll_seconds)
            except TimeoutError:
                pass

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()

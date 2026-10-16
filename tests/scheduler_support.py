"""Drain bounded lanes for unit tests; process fixtures cover actual wake timing."""

import time

from harbor_helper.execution.scheduler import Controller


def settle(store):
    controller = Controller(store)
    deadline = time.monotonic() + 10
    try:
        while True:
            controller.decide()
            if not controller.busy() and controller.completed.empty():
                return
            assert time.monotonic() < deadline, "bounded scheduler work did not settle"
            time.sleep(0.01)
    finally:
        controller.close()

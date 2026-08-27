"""Worker runtime, queue repository, and built-in deterministic handlers.

Public attributes are loaded lazily so ``python -m apps.worker.worker.main``
does not import its target module while Python is still initializing the
package. Besides removing the runpy warning, this keeps package imports free
of runtime construction side effects.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_MAIN_EXPORTS = {
    "DurableResultApplier",
    "HandlerRegistry",
    "MariaDBIdempotencyStore",
    "MariaDBResultApplier",
    "MariaDBWorkerService",
    "MemoryIdempotencyStore",
    "MemoryResultApplier",
    "MemoryWorkerService",
    "ResultApplicationError",
    "ResultApplier",
    "WorkerConfig",
    "WorkerRuntime",
    "build_default_registry",
    "build_mariadb_runtime",
}

_QUEUE_EXPORTS = {
    "ExponentialBackoff",
    "Job",
    "JobNotFound",
    "JobQueueError",
    "JobRecord",
    "MariaDBQueueRepository",
    "MemoryQueueRepository",
    "QueueRepository",
    "calculate_backoff",
}

__all__ = sorted(_MAIN_EXPORTS | _QUEUE_EXPORTS)


def __getattr__(name: str) -> Any:
    if name in _MAIN_EXPORTS:
        return getattr(import_module(".main", __name__), name)
    if name in _QUEUE_EXPORTS:
        return getattr(import_module(".queue", __name__), name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))

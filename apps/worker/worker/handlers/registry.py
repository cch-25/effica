"""Handler registry and built-in registrations."""

from __future__ import annotations

from collections.abc import Mapping

from .base import HandlerCallable, HandlerError


class HandlerRegistry:
    """Explicit mapping from persisted ``job_type`` to callable."""

    def __init__(self, handlers: Mapping[str, HandlerCallable] | None = None) -> None:
        self._handlers: dict[str, HandlerCallable] = {}
        for name, handler in (handlers or {}).items():
            self.register(name, handler)

    def register(self, job_type: str, handler: HandlerCallable, *, replace: bool = False) -> None:
        name = str(job_type).strip()
        if not name:
            raise ValueError("job_type must not be empty")
        if name in self._handlers and not replace:
            raise ValueError(f"handler already registered: {name}")
        if not callable(handler):
            raise TypeError("handler must be callable")
        self._handlers[name] = handler

    def unregister(self, job_type: str) -> None:
        self._handlers.pop(str(job_type), None)

    def get(self, job_type: str) -> HandlerCallable | None:
        return self._handlers.get(str(job_type))

    def require(self, job_type: str) -> HandlerCallable:
        handler = self.get(job_type)
        if handler is None:
            raise HandlerError(
                f"no handler registered for {job_type}",
                code="UNKNOWN_JOB_TYPE",
                details={"job_type": str(job_type)},
                retryable=False,
            )
        return handler

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers))

    def __contains__(self, job_type: object) -> bool:
        return str(job_type) in self._handlers

    def __len__(self) -> int:
        return len(self._handlers)


def build_default_registry() -> HandlerRegistry:
    # Imports are local to keep importing the registry cheap and avoid module
    # cycles while individual handlers are tested in isolation.
    from . import (
        aggregate_votes,
        analyze,
        calculate_score,
        cluster,
        crawl,
        delete_user,
        export_user,
        issue_operation,
        recommend_weights,
        render_share_card,
        simulate_weights,
    )

    modules = (
        crawl,
        cluster,
        analyze,
        aggregate_votes,
        calculate_score,
        recommend_weights,
        simulate_weights,
        render_share_card,
        export_user,
        delete_user,
    )
    registry = HandlerRegistry({module.JOB_TYPE: module.handle for module in modules})
    registry.register(issue_operation.JOB_TYPE_MERGE, issue_operation.handle_merge)
    registry.register(issue_operation.JOB_TYPE_SPLIT, issue_operation.handle_split)
    return registry

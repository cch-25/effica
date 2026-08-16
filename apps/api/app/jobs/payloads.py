"""Authoritative payload contracts for jobs crossing the API/worker boundary.

The queue deliberately stores JSON, so a job's payload needs a small, explicit
contract before it is handed to a worker.  These checks are intentionally
transport-level checks: identifiers may refer to rows that do not exist yet,
and a worker may fill expensive fields (article text, votes, or export rows)
through an injected repository lookup.  The worker handlers perform the
domain-specific validation after those lookups.

Keeping this module free of SQLAlchemy and domain models makes it safe for API
producers, worker tests, and command-line tooling to import the same rules.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


class JobPayloadError(ValueError):
    """Raised when a persisted job payload cannot satisfy its contract."""

    code = "INVALID_JOB_PAYLOAD"

    def __init__(
        self,
        message: str,
        *,
        job_type: str | None = None,
        missing: tuple[str, ...] = (),
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.job_type = job_type
        self.missing = tuple(missing)
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        details = dict(self.details)
        if self.job_type:
            details.setdefault("job_type", self.job_type)
        if self.missing:
            details.setdefault("missing", list(self.missing))
        return {"code": self.code, "message": str(self), "details": details}


@dataclass(frozen=True)
class JobPayloadContract:
    """Transport-level description for one built-in job type."""

    job_type: str
    required_any: tuple[tuple[str, ...], ...] = ()
    required_all: tuple[str, ...] = ()
    validator: Callable[[Mapping[str, Any]], None] | None = None

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise JobPayloadError(
                "job payload must be a JSON object",
                job_type=self.job_type,
            )
        value = dict(payload)
        missing = [key for key in self.required_all if _blank(value.get(key))]
        for alternatives in self.required_any:
            if not any(not _blank(value.get(key)) for key in alternatives):
                missing.append(" or ".join(alternatives))
        if missing:
            raise JobPayloadError(
                "required job payload is missing",
                job_type=self.job_type,
                missing=tuple(missing),
            )
        if self.validator is not None:
            try:
                self.validator(value)
            except JobPayloadError:
                raise
            except (TypeError, ValueError) as exc:
                raise JobPayloadError(
                    str(exc) or "invalid job payload",
                    job_type=self.job_type,
                ) from exc
        return value


def _blank(value: Any) -> bool:
    return value is None or value == ""


def _one_of(value: Any, choices: set[str], field: str) -> None:
    if value is None:
        return
    candidate = str(value).upper()
    if candidate not in choices:
        raise JobPayloadError(
            f"{field} must be one of {sorted(choices)}",
            details={field: value},
        )


def _positive_int(value: Any, field: str) -> None:
    if value is None:
        return
    try:
        if int(value) < 1:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise JobPayloadError(f"{field} must be a positive integer", details={field: value}) from exc


def _validate_crawl(payload: Mapping[str, Any]) -> None:
    _one_of(payload.get("source_type"), {"API", "RSS", "CRAWLER"}, "source_type")
    source_type = str(payload.get("source_type", "API")).upper()
    if source_type == "CRAWLER":
        for field in ("policy_status", "robots_status", "terms_status"):
            if str(payload.get(field, "UNKNOWN")).upper() != "APPROVED":
                raise JobPayloadError(
                    "crawler policy, robots and terms approval are required",
                    details={"field": field},
                )


def _validate_articles(payload: Mapping[str, Any]) -> None:
    articles = payload.get("articles")
    article_ids = payload.get("article_ids")
    if articles is not None and (not isinstance(articles, (list, tuple)) or not articles):
        raise JobPayloadError("articles must be a non-empty list")
    if article_ids is not None and (not isinstance(article_ids, (list, tuple)) or not article_ids):
        raise JobPayloadError("article_ids must be a non-empty list")


def _validate_votes(payload: Mapping[str, Any]) -> None:
    votes = payload.get("votes")
    if votes is not None and not isinstance(votes, (list, tuple)):
        raise JobPayloadError("votes must be a list")


def _validate_analyze(payload: Mapping[str, Any]) -> None:
    text = payload.get("text")
    if text is not None and not isinstance(text, str):
        raise JobPayloadError("text must be a string")


def _validate_score(payload: Mapping[str, Any]) -> None:
    components = payload.get("components")
    if components is not None and not isinstance(components, Mapping):
        raise JobPayloadError("components must be an object")
    weights = payload.get("weights")
    if weights is not None and not isinstance(weights, Mapping):
        raise JobPayloadError("weights must be an object")


def _validate_simulation(payload: Mapping[str, Any]) -> None:
    windows = payload.get("windows")
    if windows is not None:
        if not isinstance(windows, (list, tuple)) or not windows:
            raise JobPayloadError("windows must be a non-empty list")
        if any(int(window) <= 0 for window in windows):
            raise JobPayloadError("windows must contain positive integers")


def _validate_render(payload: Mapping[str, Any]) -> None:
    snapshot = payload.get("snapshot")
    if snapshot is not None and not isinstance(snapshot, Mapping):
        raise JobPayloadError("snapshot must be an object")


def _validate_export(payload: Mapping[str, Any]) -> None:
    records = payload.get("records")
    if records is not None and not isinstance(records, Mapping):
        raise JobPayloadError("records must be an object")


def _validate_delete(payload: Mapping[str, Any]) -> None:
    # ``confirmation`` is accepted as the API-facing spelling; the worker
    # handler normalizes it to ``confirmed`` before executing the operation.
    confirmed = payload.get("confirmed")
    confirmation = payload.get("confirmation")
    if confirmed is not True and confirmation != "DELETE MY ACCOUNT":
        raise JobPayloadError(
            "account deletion requires explicit confirmation",
            details={"required": "confirmed=true or confirmation='DELETE MY ACCOUNT'"},
        )


def _validate_merge(payload: Mapping[str, Any]) -> None:
    if str(payload["source_issue_id"]) == str(payload["target_issue_id"]):
        raise JobPayloadError("source and target issues must differ")


def _validate_split(payload: Mapping[str, Any]) -> None:
    article_ids = payload.get("article_ids")
    if not isinstance(article_ids, (list, tuple)) or not article_ids:
        raise JobPayloadError("article_ids must be a non-empty list")
    if len({str(item) for item in article_ids}) != len(article_ids):
        raise JobPayloadError("article_ids must be unique")


JOB_PAYLOAD_CONTRACTS: dict[str, JobPayloadContract] = {
    "crawl": JobPayloadContract("crawl", required_any=(("url", "source_id"),), validator=_validate_crawl),
    "cluster": JobPayloadContract(
        "cluster", required_any=(("articles", "article_ids"),), validator=_validate_articles
    ),
    "analyze": JobPayloadContract(
        "analyze", required_any=(("text", "article_version_id"),), validator=_validate_analyze
    ),
    "aggregate_votes": JobPayloadContract(
        "aggregate_votes", required_any=(("votes", "article_id"),), validator=_validate_votes
    ),
    "calculate_score": JobPayloadContract(
        "calculate_score", required_any=(("components", "article_version_id"),), validator=_validate_score
    ),
    "recommend_weights": JobPayloadContract(
        "recommend_weights", required_any=(("metrics", "outcomes", "recommendation_id"),)
    ),
    "simulate_weights": JobPayloadContract(
        "simulate_weights", required_any=(("weights", "recommendation_id", "weight_id"),), validator=_validate_simulation
    ),
    "render_share_card": JobPayloadContract(
        "render_share_card", required_all=("share_card_id",), validator=_validate_render
    ),
    "export_user": JobPayloadContract(
        "export_user", required_all=("user_id",), validator=_validate_export
    ),
    "delete_user": JobPayloadContract(
        "delete_user", required_all=("user_id",), validator=_validate_delete
    ),
    "merge_issue": JobPayloadContract(
        "merge_issue", required_all=("source_issue_id", "target_issue_id"), validator=_validate_merge
    ),
    "split_issue": JobPayloadContract(
        "split_issue", required_all=("issue_id", "article_ids"), validator=_validate_split
    ),
}


def get_job_payload_contract(job_type: Any) -> JobPayloadContract | None:
    """Return the built-in contract, or ``None`` for extension job types."""

    normalized = getattr(job_type, "value", job_type)
    return JOB_PAYLOAD_CONTRACTS.get(str(normalized).strip())


def validate_job_payload(job_type: Any, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and copy a payload before queue insertion or handler invoke.

    Unknown job types remain extensible; a custom registry owns their schema.
    """

    contract = get_job_payload_contract(job_type)
    if contract is None:
        if not isinstance(payload, Mapping):
            raise JobPayloadError("job payload must be a JSON object", job_type=str(job_type))
        return dict(payload)
    try:
        return contract.validate(payload)
    except JobPayloadError as exc:
        if exc.job_type is None:
            exc.job_type = contract.job_type
        raise


# Concise aliases used by worker integrations and API callers.
validate_payload = validate_job_payload
JOB_PAYLOAD_SCHEMAS = JOB_PAYLOAD_CONTRACTS


__all__ = [
    "JOB_PAYLOAD_CONTRACTS",
    "JOB_PAYLOAD_SCHEMAS",
    "JobPayloadContract",
    "JobPayloadError",
    "get_job_payload_contract",
    "validate_job_payload",
    "validate_payload",
]

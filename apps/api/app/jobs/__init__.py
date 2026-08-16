"""Shared asynchronous-job contracts used by the API and worker.

The queue itself lives in :mod:`apps.worker.worker.queue`; this package only
contains transport-neutral types and the producer used by API services.  It
is intentionally independent of the API's database model package so that the
worker can be imported without creating a FastAPI application.
"""

from .payloads import (
    JOB_PAYLOAD_CONTRACTS,
    JOB_PAYLOAD_SCHEMAS,
    JobPayloadContract,
    JobPayloadError,
    get_job_payload_contract,
    validate_job_payload,
    validate_payload,
)
from .producer import JobProducer, MariaDBJobProducer
from .types import (
    DEFAULT_MAX_ATTEMPTS,
    JobEnvelope,
    JobStatus,
    JobSubmission,
    JobType,
    canonical_payload_json,
    generate_job_id,
    normalize_job_type,
    utc_now,
)

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "JOB_PAYLOAD_CONTRACTS",
    "JOB_PAYLOAD_SCHEMAS",
    "JobEnvelope",
    "JobPayloadContract",
    "JobPayloadError",
    "JobProducer",
    "JobStatus",
    "JobSubmission",
    "JobType",
    "MariaDBJobProducer",
    "canonical_payload_json",
    "generate_job_id",
    "get_job_payload_contract",
    "normalize_job_type",
    "utc_now",
    "validate_job_payload",
    "validate_payload",
]

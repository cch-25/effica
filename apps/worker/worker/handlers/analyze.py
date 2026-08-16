"""Deterministic three-model content-first analysis for offline vertical slices."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.analysis import (
    AssessmentInput,
    LLMProvider,
    ProviderError,
    ProviderSchemaError,
    ensemble_assessments,
    make_stub_providers,
)

from .base import (
    HandlerContext,
    HandlerError,
    HandlerResult,
    NonRetryableHandlerError,
    lookup_service,
    require_mapping,
)

JOB_TYPE = "analyze"


async def handle(
    payload: Mapping[str, Any], context: HandlerContext | None = None
) -> HandlerResult:
    require_mapping(payload)
    source = dict(payload)
    text_value = source.get("text")
    if text_value in (None, ""):
        version_id = source.get("article_version_id") or source.get("article_id")
        loaded = await lookup_service(
            context,
            (
                "article_version_lookup",
                "article_lookup",
                "load_article_version",
                "article_versions",
            ),
            identifier=version_id,
            payload=source,
        )
        if isinstance(loaded, Mapping):
            source = {**dict(loaded), **source}
            text_value = source.get("text") or source.get("content") or source.get("body")
    text = str(text_value or "").strip()
    if not text:
        raise NonRetryableHandlerError(
            "article text is required directly or through article_version lookup",
            code="INVALID_ANALYSIS_PAYLOAD",
            details={"required_any": ["text", "article_version_id"]},
        )
    article_version_id = str(
        source.get("article_version_id") or (context.job_id if context else "fixture-version")
    )
    assessment_input = AssessmentInput(
        article_version_id=article_version_id,
        title=str(source.get("title") or "Fixture article"),
        content=text,
        source_name=str(source["source_name"]) if source.get("source_name") else None,
        source_url=str(source["source_url"]) if source.get("source_url") else None,
        author=str(source["author"]) if source.get("author") else None,
    )
    prompt_version = str(source.get("prompt_version", "content-first-v1"))
    configured = None if context is None else context.services.get("analysis_providers")
    providers = (
        list(configured)
        if isinstance(configured, (list, tuple))
        and len(configured) >= 2
        and all(isinstance(item, LLMProvider) for item in configured)
        else make_stub_providers(3)
    )
    assessments = []
    provider_errors: list[dict[str, Any]] = []
    for provider in providers:
        try:
            assessments.append(provider.analyze_article(assessment_input, prompt_version))
        except ProviderError as exc:
            provider_errors.append(
                {
                    "model_alias": provider.config.alias,
                    "code": exc.code,
                    "retryable": not isinstance(exc, ProviderSchemaError),
                }
            )
    minimum = int(source.get("min_success_models", 2))
    if len(assessments) < minimum:
        raise HandlerError(
            "minimum successful analysis providers not reached",
            code="MINIMUM_ANALYSIS_PROVIDERS_NOT_REACHED",
            details={"minimum": minimum, "successes": len(assessments), "errors": provider_errors},
            retryable=any(error["retryable"] for error in provider_errors),
        )
    ensemble = ensemble_assessments(
        assessments,
        min_success_models=minimum,
        max_spread=float(source.get("max_spread", 100)),
    )
    return HandlerResult(
        value={
            "article_version_id": article_version_id,
            "prompt_version": prompt_version,
            "assessments": [item.model_dump(mode="json") for item in assessments],
            "ensemble": ensemble.as_dict(),
            "raw_response": [item.model_dump(mode="json") for item in assessments],
            "provider_errors": provider_errors,
        },
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle

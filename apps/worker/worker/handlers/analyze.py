"""Single-model content-first analysis with an offline deterministic fallback."""

from __future__ import annotations

import inspect
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
        and len(configured) >= 1
        and all(isinstance(item, LLMProvider) for item in configured)
        else []
    )
    owns_providers = False
    factory = None if context is None else context.services.get("analysis_provider_factory")
    if not providers and callable(factory):
        built = factory()
        if inspect.isawaitable(built):
            built = await built
        if not isinstance(built, LLMProvider):
            raise NonRetryableHandlerError(
                "analysis provider factory returned an invalid provider",
                code="INVALID_ANALYSIS_PROVIDER",
            )
        providers = [built]
        owns_providers = True
    if not providers:
        providers = make_stub_providers(1)
    assessments = []
    provider_errors: list[dict[str, Any]] = []
    try:
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
    finally:
        if owns_providers:
            for provider in providers:
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
    # The constrained runtime intentionally uses one GPT configuration. Old
    # queued payloads may still request two or three providers, so do not let
    # that historical policy make every migrated job fail.
    minimum = 1
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
    serialized_assessments: list[dict[str, Any]] = []
    provider_by_alias = {provider.config.alias: provider for provider in providers}
    for assessment in assessments:
        provider = provider_by_alias[assessment.model_alias]
        item = assessment.model_dump(mode="json")
        if provider.config.model_alias_id:
            item["model_alias_id"] = provider.config.model_alias_id
        item["provider"] = "openai" if provider.config.endpoint else "deterministic-stub"
        serialized_assessments.append(item)
    return HandlerResult(
        value={
            "article_version_id": article_version_id,
            "prompt_version": prompt_version,
            "assessments": serialized_assessments,
            "ensemble": ensemble.as_dict(),
            "raw_response": serialized_assessments,
            "provider_errors": provider_errors,
        },
        side_effect_key=(context.idempotency_key if context else None),
    )


run = handle

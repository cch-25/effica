"""Single-model content-first analysis with an offline deterministic fallback."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from typing import Any

from apps.api.app.domains.analysis import (
    AssessmentInput,
    LLMProvider,
    ProviderConfigurationError,
    ProviderError,
    ProviderHTTPError,
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
    prompt_value = source.get("prompt_version", "bias-sensationalism-v1")
    if not isinstance(prompt_value, str) or not prompt_value.strip():
        raise NonRetryableHandlerError(
            "prompt_version must be a non-empty string",
            code="INVALID_ANALYSIS_PAYLOAD",
            details={"field": "prompt_version"},
        )
    prompt_version = prompt_value.strip()
    configured = None if context is None else context.services.get("analysis_providers")
    if configured is not None and (
        not isinstance(configured, (list, tuple))
        or not configured
        or not all(isinstance(item, LLMProvider) for item in configured)
    ):
        raise NonRetryableHandlerError(
            "analysis_providers must contain valid providers",
            code="INVALID_ANALYSIS_PROVIDER",
        )
    providers = list(configured) if isinstance(configured, (list, tuple)) else []
    owns_providers = False
    factory = None if context is None else context.services.get("analysis_provider_factory")
    if not providers and callable(factory):
        try:
            try:
                factory_signature = inspect.signature(factory)
                supports_attempt = "attempt" in factory_signature.parameters or any(
                    parameter.kind == parameter.VAR_KEYWORD
                    for parameter in factory_signature.parameters.values()
                )
            except (TypeError, ValueError):
                supports_attempt = False
            built = (
                factory(attempt=context.attempt if context is not None else 1)
                if supports_attempt
                else factory()
            )
            if inspect.isawaitable(built):
                built = await built
        except ProviderError as exc:
            raise HandlerError(
                "analysis provider initialization failed",
                code=exc.code,
                details={"stage": "provider_factory"},
                retryable=_provider_error_is_retryable(exc),
            ) from exc
        except (TypeError, ValueError) as exc:
            raise NonRetryableHandlerError(
                "analysis provider configuration is invalid",
                code="INVALID_ANALYSIS_PROVIDER",
                details={"stage": "provider_factory"},
            ) from exc
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
                assessments.append(
                    await asyncio.to_thread(
                        provider.analyze_article,
                        assessment_input,
                        prompt_version,
                    )
                )
            except ProviderError as exc:
                retryable = _provider_error_is_retryable(exc)
                provider_errors.append(
                    {
                        "model_alias": provider.config.alias,
                        "code": exc.code,
                        "retryable": retryable,
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
        provider = provider_by_alias.get(assessment.model_alias)
        if provider is None:
            raise NonRetryableHandlerError(
                "provider returned an unknown model alias",
                code="INVALID_ANALYSIS_PROVIDER_OUTPUT",
                details={"model_alias": assessment.model_alias},
            )
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


def _provider_error_is_retryable(exc: ProviderError) -> bool:
    """Preserve provider-specific retry semantics at the queue boundary."""

    if isinstance(exc, ProviderHTTPError):
        return exc.retryable
    if isinstance(exc, ProviderConfigurationError):
        return False
    # A structured-output rejection is an upstream generation failure. A
    # later request can succeed, unlike invalid handler input which is
    # rejected before a provider is called.
    if isinstance(exc, ProviderSchemaError):
        return True
    return bool(getattr(exc, "retryable", True))

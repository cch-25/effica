"""Public aggregates for a user's news consumption and questionnaire result."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from numbers import Real
from typing import Any

CONSUMPTION_DIVERSITY_POLICY_VERSION = "consumption-diversity-v1"
NEWS_CONSUMPTION_SNAPSHOT_VERSION = "news-consumption-v2"


def article_perspective(value: float) -> str:
    """Place an article score into the three public political-perspective bands."""

    numeric = float(value)
    if not math.isfinite(numeric) or not -100 <= numeric <= 100:
        raise ValueError("article perspective must be finite and in [-100,100]")
    if numeric < -10:
        return "negative_x"
    if numeric > 10:
        return "positive_x"
    return "center"


def consumption_diversity(article_x_values: Iterable[float]) -> dict[str, Any]:
    """Score distinct, classified articles by volume and perspective balance.

    Twelve classified articles give full volume credit. Shannon entropy across
    the three bands supplies the balance factor, so repeatedly consuming a
    single perspective never masquerades as diverse consumption.
    """

    counts = {"negative_x": 0, "center": 0, "positive_x": 0}
    for value in article_x_values:
        counts[article_perspective(value)] += 1
    article_count = sum(counts.values())
    if article_count == 0:
        score = 0
    else:
        entropy = -sum(
            proportion * math.log(proportion)
            for count in counts.values()
            if (proportion := count / article_count) > 0
        ) / math.log(3)
        volume = min(1.0, article_count / 12.0)
        score = round(100 * entropy * volume)
    return {
        "diversity_score": score,
        "diversity_article_count": article_count,
        "diversity_perspective_counts": counts,
        "diversity_policy_version": CONSUMPTION_DIVERSITY_POLICY_VERSION,
    }


def ideology_snapshot(
    *,
    source_version: str | None,
    required_version: str,
    x: int | float | None = None,
    y: int | float | None = None,
    z: int | float | None = None,
    confidence: int | float | None = None,
) -> dict[str, Any]:
    """Return questionnaire-only ideology, neutral for missing/legacy profiles."""

    completed = source_version == required_version and all(
        value is not None for value in (x, y, z, confidence)
    )
    if not completed:
        return {
            "completed": False,
            "x": 0,
            "y": 0,
            "z": 0,
            "confidence": 0.0,
            "questionnaire_version": None,
            "questionnaire_status": "not_completed",
        }
    coordinates = [round(float(value)) for value in (x, y, z)]
    if any(not -100 <= value <= 100 for value in coordinates):
        raise ValueError("ideology coordinates must be in [-100,100]")
    safe_confidence = float(confidence)
    if not math.isfinite(safe_confidence) or not 0 <= safe_confidence <= 1:
        raise ValueError("ideology confidence must be in [0,1]")
    return {
        "completed": True,
        "x": coordinates[0],
        "y": coordinates[1],
        "z": coordinates[2],
        "confidence": round(safe_confidence, 4),
        "questionnaire_version": source_version,
        "questionnaire_status": "beta",
    }


def public_snapshot_view(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    """Never reinterpret a legacy behavioural coordinate as questionnaire ideology."""

    source = dict(snapshot) if isinstance(snapshot, Mapping) else {}
    raw_publication_consent = source.get("publication_consent")
    publication_consent = (
        {
            key: raw_publication_consent.get(key)
            for key in ("confirmation_version", "confirmed_at")
            if isinstance(raw_publication_consent.get(key), str)
        }
        if isinstance(raw_publication_consent, Mapping)
        else None
    )
    if source.get("snapshot_schema_version") == NEWS_CONSUMPTION_SNAPSHOT_VERSION:
        raw_counts = source.get("diversity_perspective_counts")
        counts = raw_counts if isinstance(raw_counts, Mapping) else {}
        raw_ideology = source.get("ideology")
        ideology_source = raw_ideology if isinstance(raw_ideology, Mapping) else {}
        questionnaire_version = ideology_source.get("questionnaire_version")
        completed = (
            ideology_source.get("completed") is True
            and isinstance(questionnaire_version, str)
            and bool(questionnaire_version.strip())
            and ideology_source.get("questionnaire_status") == "beta"
        )
        try:
            ideology = (
                ideology_snapshot(
                    source_version=questionnaire_version,
                    required_version=questionnaire_version,
                    x=ideology_source.get("x"),
                    y=ideology_source.get("y"),
                    z=ideology_source.get("z"),
                    confidence=ideology_source.get("confidence"),
                )
                if completed
                else ideology_snapshot(source_version=None, required_version="")
            )
        except (TypeError, ValueError):
            ideology = ideology_snapshot(source_version=None, required_version="")

        def bounded_int(value: Any, *, maximum: int | None = None) -> int:
            if isinstance(value, bool) or not isinstance(value, Real):
                return 0
            numeric = float(value)
            if not math.isfinite(numeric) or not numeric.is_integer() or numeric < 0:
                return 0
            if maximum is not None and numeric > maximum:
                return 0
            return int(numeric)

        return {
            "snapshot_schema_version": NEWS_CONSUMPTION_SNAPSHOT_VERSION,
            "diversity_score": bounded_int(
                source.get("diversity_score"), maximum=100
            ),
            "diversity_article_count": bounded_int(
                source.get("diversity_article_count")
            ),
            "diversity_perspective_counts": {
                key: bounded_int(counts.get(key))
                for key in ("negative_x", "center", "positive_x")
            },
            "diversity_policy_version": (
                CONSUMPTION_DIVERSITY_POLICY_VERSION
                if source.get("diversity_policy_version")
                == CONSUMPTION_DIVERSITY_POLICY_VERSION
                else None
            ),
            "ideology": ideology,
            "created_at": (
                source.get("created_at")
                if isinstance(source.get("created_at"), str)
                else None
            ),
            "political_data_publication_confirmed": bool(
                source.get("political_data_publication_confirmed", False)
            ),
            "publication_consent": publication_consent,
        }
    return {
        "snapshot_schema_version": "legacy-v1",
        "legacy": True,
        "legacy_notice": "This card predates the news-consumption profile contract.",
        "diversity_score": 0,
        "diversity_article_count": 0,
        "diversity_perspective_counts": {
            "negative_x": 0,
            "center": 0,
            "positive_x": 0,
        },
        "diversity_policy_version": None,
        "ideology": ideology_snapshot(source_version=None, required_version=""),
        "created_at": (
            source.get("created_at")
            if isinstance(source.get("created_at"), str)
            else None
        ),
        "political_data_publication_confirmed": bool(
            source.get("political_data_publication_confirmed", False)
        ),
        "publication_consent": publication_consent,
    }


__all__ = [
    "CONSUMPTION_DIVERSITY_POLICY_VERSION",
    "NEWS_CONSUMPTION_SNAPSHOT_VERSION",
    "article_perspective",
    "consumption_diversity",
    "ideology_snapshot",
    "public_snapshot_view",
]

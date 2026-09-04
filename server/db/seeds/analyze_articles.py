"""Generate resumable two-axis LLM assessments for the real article snapshot."""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from apps.api.app.core.config import get_settings
from apps.api.app.domains.analysis import AssessmentInput, HttpLLMProvider, ProviderConfig

from .seed import ARTICLE_DATA, _load_articles, _stable_ulid

PROMPT_VERSION = "bias-sensationalism-v1"
MODEL_ALIAS = "openai-bias-v1"


def _write_articles(path: Path, articles: list[dict[str, Any]]) -> None:
    path.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _analyze(row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    settings = get_settings()
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY가 필요합니다")
    url = row["canonical_url"]
    provider = HttpLLMProvider(
        ProviderConfig(
            alias=MODEL_ALIAS,
            actual_model_id=settings.llm_model,
            endpoint=settings.openai_endpoint,
            api_key=settings.openai_api_key,
            reasoning_effort=settings.llm_reasoning_effort,
            timeout_seconds=180,
            max_retries=3,
            retry_backoff_seconds=1,
            max_backoff_seconds=8,
            rate_limit_per_minute=120,
            circuit_failure_threshold=4,
        )
    )
    try:
        result = provider.analyze_article(
            AssessmentInput(
                article_version_id=_stable_ulid("version", url),
                title=row["title"],
                content=row["body_text"],
                source_name=row["source_name"],
                source_url=url,
                author=row.get("author"),
            ),
            PROMPT_VERSION,
        )
    finally:
        provider.close()
    return url, {
        "model_alias": MODEL_ALIAS,
        "actual_model_id": result.actual_model_id,
        "prompt_version": PROMPT_VERSION,
        "bias": result.x,
        "sensationalism": result.sensationalism,
        "confidence": result.confidence,
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "rationale_summary": result.rationale_summary,
        "token_usage": result.token_usage,
        "latency_ms": result.latency_ms,
        "status": result.status.value,
    }


def analyze_all(*, workers: int, force: bool) -> int:
    articles = _load_articles(require_assessments=False)
    pending = [row for row in articles if force or not row.get("llm_assessment")]
    if not pending:
        print(f"LLM 평가가 이미 완료되었습니다: {len(articles)}개")
        return 0

    by_url = {row["canonical_url"]: row for row in articles}
    failures: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_analyze, row): row["canonical_url"] for row in pending}
        completed = len(articles) - len(pending)
        for future in as_completed(futures):
            url = futures[future]
            try:
                result_url, assessment = future.result()
                by_url[result_url]["llm_assessment"] = assessment
                completed += 1
                _write_articles(ARTICLE_DATA, articles)
                print(f"LLM 평가 완료 {completed}/{len(articles)}")
            except Exception as exc:  # Provider errors are already redacted.
                failures.append((url, type(exc).__name__))
                print(f"LLM 평가 실패: {url} ({type(exc).__name__})")

    if failures:
        print(f"실패 {len(failures)}개; 성공 결과는 저장되어 재실행 시 이어서 처리됩니다")
        return 1
    print(f"LLM 평가 전체 완료: {len(articles)}개")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 기사 전체를 두 축으로 LLM 평가합니다")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error("--workers는 1~12 범위여야 합니다")
    return analyze_all(workers=args.workers, force=args.force)


if __name__ == "__main__":
    raise SystemExit(main())

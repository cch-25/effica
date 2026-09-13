"""Publisher UI must not enter article content or public analysis evidence."""

import json

import pytest

from apps.api.app.domains.analysis.provider import validate_public_evidence
from apps.api.app.domains.analysis.schema import Evidence
from apps.api.app.domains.content import APIAdapter, CrawlerAdapter, CrawlerPolicyGuard, RSSAdapter
from apps.api.app.domains.content.boilerplate import evidence_contains_boilerplate
from apps.api.app.domains.content.trust import public_assessment_evidence, public_assessment_summary

CHROME = "등록 2026.09.13 09:00:00 구글에서 선호하는 매체로 추가 작게 크게"
REPORTING = "법원은 구체적인 사실관계를 토대로 판결했다."


def crawl(html: str):
    return CrawlerAdapter("source", CrawlerPolicyGuard("APPROVED", "APPROVED")).parse(
        {"url": "https://example.test/news/1", "html": html}
    )[0]


@pytest.mark.parametrize("chrome", [
    CHROME,
    "입력 : 2026-09-13 09:00 수정 : 2026-09-13 10:00",
    "구글에서 선호하는 매체로 추가",
    "작게 크게",
    "글자 크기 조절 | 공유하기 | 인쇄하기 | URL 복사 | 구독하기",
])
def test_controls_are_excluded_from_collected_body_and_public_quotes(chrome: str) -> None:
    assert crawl(f"<article><p>{chrome}</p><p>{REPORTING}</p></article>").body == REPORTING
    assert evidence_contains_boilerplate(chrome)
    assert public_assessment_evidence([{"quote": chrome}]) == []


def test_semantic_controls_and_toolbar_subtrees_are_skipped_without_changing_hash() -> None:
    def html(counter: int) -> str:
        return f"""<article><div class="article-body">
            <div role="toolbar"><a>Unknown action {counter}</a></div>
            <button><span>Another action {counter}</span></button>
            <a role="button">Custom action {counter}</a>
            <div class="article-tools"><p>Font menu {counter}</p></div>
            <p>{REPORTING}<button>Print {counter}</button></p>
            </div></article>"""

    first, second = crawl(html(1)), crawl(html(2))
    assert first.body == REPORTING
    assert first.content_hash == second.content_hash


@pytest.mark.parametrize("format", ["api-text", "api-html", "rss", "json-ld", "html"])
def test_all_ingestion_formats_remove_screen_text(format: str) -> None:
    body = f"{CHROME}\n{REPORTING}\n공유하기"
    html_body = f"<p>{CHROME}</p><p>{REPORTING}</p><button>Unknown action</button>"
    if format.startswith("api"):
        article = APIAdapter().parse({
            "url": "https://example.test/news/1", "title": "판결 보도",
            "body": html_body if format == "api-html" else body,
        })[0]
    elif format == "rss":
        article = RSSAdapter().parse(f"""<rss><channel><item><title>판결 보도</title>
            <link>https://example.test/news/1</link>
            <description><![CDATA[{html_body}]]></description></item></channel></rss>""")[0]
    elif format == "json-ld":
        payload = json.dumps({"@type": "NewsArticle", "headline": "판결 보도", "articleBody": body})
        article = crawl(f'<script type="application/ld+json">{payload}</script>')
    else:
        article = crawl(f"<article>{html_body}</article>")
    assert article.body == REPORTING


def test_flattened_legacy_prefix_is_removed_but_mixed_evidence_is_not_rewritten() -> None:
    text = f"{CHROME} {REPORTING}"
    article = APIAdapter().parse({
        "url": "https://example.test/news/1", "title": "판결 보도", "body": text,
    })[0]
    assert article.body == REPORTING
    assert public_assessment_evidence([{"quote": text}]) == []


@pytest.mark.parametrize("text", [
    "구글에서 선호하는 매체로 추가하는 기능이 도입됐다.",
    "구글에서 선호하는 매체로 추가 기능을 도입했다고 밝혔다.",
    "구글은 '선호하는 매체로 추가' 버튼을 제공한다고 밝혔다.",
    "크게 달라진 판결 기준을 설명했다.",
    "등록 시각은 2026.09.13 09:00:00으로 확인됐다.",
    "공유하기 기능이 개인정보에 미치는 영향을 조사했다.",
    "기사입력 시스템을 개선했다고 밝혔다.",
    "The article explains how to change font size and print documents.",
    "첫 번째 문장.\n  두 번째 문장.",
])
def test_reporting_about_controls_and_dates_is_preserved(text: str) -> None:
    evidence = {"quote": text, "start": 0, "end": len(text)}
    assert not evidence_contains_boilerplate(text)
    assert public_assessment_evidence([evidence]) == [evidence]
    assert crawl(f"<article><p>{text}</p></article>").body == " ".join(text.split())


def test_inline_emphasis_is_not_mistaken_for_a_font_button() -> None:
    assert crawl("<article><p>판결 기준이 <strong>크게</strong> 달라졌다.</p></article>").body == (
        "판결 기준이 크게 달라졌다."
    )


def test_provider_drops_chrome_and_preserves_real_evidence_offsets() -> None:
    content = f"{CHROME} {REPORTING}"
    valid_start = len(CHROME) + 1
    quotes = [
        Evidence(article_version_id="v1", start=0, end=len(CHROME), quote=CHROME,
                 rationale="화면 문구가 잘못 선택됐다."),
        Evidence(article_version_id="v1", start=valid_start, end=len(content), quote=REPORTING,
                 rationale="판결의 사실관계 중심 서술을 뒷받침한다."),
    ]
    result = validate_public_evidence(quotes, article_version_id="v1", source_text=content)
    assert result == [quotes[1]]
    assert content[result[0].start:result[0].end] == REPORTING
    assert validate_public_evidence(quotes[:1], article_version_id="v1", source_text=content) == []


def test_legacy_public_filter_runs_before_limit_and_excludes_contaminated_rationales() -> None:
    junk = [{"quote": CHROME, "rationale": "노출하면 안 되는 근거"}] * 5
    valid = [{"quote": REPORTING, "rationale": "사실관계를 설명한다."}]
    assert public_assessment_evidence({"evidence": junk + valid}) == valid
    assert public_assessment_summary(junk + valid) == "사실관계를 설명한다."
    assert public_assessment_evidence({"evidence": junk}) == []

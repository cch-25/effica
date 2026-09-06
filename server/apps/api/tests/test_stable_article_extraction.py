"""Regression checks for volatile page chrome creating paid article versions."""

from apps.api.app.domains.content import CrawlerAdapter, CrawlerPolicyGuard


def _parse(html: str, *, discover: bool = False):
    return CrawlerAdapter(
        "source",
        CrawlerPolicyGuard("APPROVED", "APPROVED"),
        {"discover_links": discover},
    ).parse({"url": "https://example.test/press", "html": html})


def test_dynamic_subtrees_do_not_change_article_content_hash() -> None:
    def document(counter: int) -> str:
        return f"""
        <title>Government announces industrial policy</title>
        <main><p>Site updated {counter}</p>
          <article><h1>Government announces industrial policy</h1>
            <div class="article-body"><p>Funding increases by 30 percent.</p>
              <div class="view-count"><span>{counter}</span></div>
              <div class="related-articles"><p>Recommendation {counter}</p></div>
              <div class="comments"><p>Reader comment {counter}</p></div>
              <p>Parliament reviews the proposal next week.</p>
              <span hidden>Unstable widget {counter}</span>
            </div>
          </article>
          <p>Popular article {counter}</p>
        </main>"""

    first = _parse(document(100))[0]
    second = _parse(document(101))[0]
    assert first.body == "Funding increases by 30 percent. Parliament reviews the proposal next week."
    assert first.content_hash == second.content_hash


def test_real_body_changes_still_change_hash_and_marker_substrings_are_preserved() -> None:
    first = _parse("""<article><h1>Candidate policy</h1><div class="candidate">
        <p>Candidate proposes a capital allowance of 100 dollars.</p>
        </div></article>""")[0]
    second = _parse("""<article><h1>Candidate policy</h1><div class="candidate">
        <p>Candidate proposes a capital allowance of 200 dollars.</p>
        </div></article>""")[0]
    assert "100 dollars" in first.body
    assert "200 dollars" in second.body
    assert first.content_hash != second.content_hash


def test_main_and_description_do_not_turn_government_index_into_article() -> None:
    html = """<title>보도자료 - 위원회 소식 - 알림마당 - 금융위원회</title>
        <meta name="description" content="Daily changing government index">
        <main><p>조회수 100 최신 자료 목록</p>
          <a href="/press/1">금융 지원 정책 발표</a>
          <a href="/press/2">투자 지원 정책 발표</a></main>"""
    assert _parse(html)[0].body == ""
    discovered = _parse(html, discover=True)
    assert [article.url for article in discovered] == [
        "https://example.test/press/1", "https://example.test/press/2"
    ]
    assert all(not article.body for article in discovered)


def test_json_ld_body_is_preserved_even_when_site_title_is_generic() -> None:
    html = """<title>중소벤처기업부</title><script type="application/ld+json">
        {"@type":"NewsArticle", "articleBody":"A substantive official policy announcement."}
        </script>"""
    assert _parse(html)[0].body == "A substantive official policy announcement."


def test_void_tags_do_not_hide_following_article_content() -> None:
    article = _parse("""<article><div class="article-body"><img class="related" src="x">
        <p>The real article follows the image.</p><br><p>Its second paragraph.</p>
        </div></article>""")[0]
    assert article.body == "The real article follows the image. Its second paragraph."


def test_mixed_direct_text_and_paragraphs_keep_document_order() -> None:
    article = _parse("""<div class="article-body">Opening sentence.
        <p>Middle paragraph.</p>Closing sentence.</div>""")[0]
    assert article.body == "Opening sentence. Middle paragraph. Closing sentence."

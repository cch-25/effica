from __future__ import annotations

from apps.api.app.domains.content import APIAdapter, CrawlerAdapter, CrawlerPolicyGuard, RSSAdapter


def test_api_adapter_reads_nested_json_api_attributes_and_configured_paths() -> None:
    payload = {
        "response": {
            "items": [
                {
                    "id": "n-1",
                    "attributes": {
                        "headline": "A headline",
                        "content": {"html": "<p>Article body</p>"},
                        "published": "2025-01-02T03:04:05Z",
                        "author": {"name": "Reporter"},
                    },
                    "path": "/news/1",
                }
            ]
        }
    }
    article = APIAdapter(
        "source",
        {
            "items_path": "response.items",
            "fields": {"url": "path", "title": "headline"},
            "base_url": "https://example.test",
        },
    ).parse(payload)[0]
    assert article.url == "https://example.test/news/1"
    assert article.title == "A headline"
    assert article.body == "Article body"
    assert article.author == "Reporter"
    assert article.external_id == "n-1"


def test_rss_and_atom_nested_fields_are_normalized() -> None:
    payload = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Atom title</title>
        <link rel="self" href="https://example.test/feed"/>
        <link rel="alternate" type="text/html" href="/story"/>
        <id>atom-1</id>
        <updated>2025-01-02T03:04:05Z</updated>
        <author><name>Atom author</name></author>
        <content type="html"><![CDATA[<p>Atom <b>body</b></p>]]></content>
      </entry>
    </feed>"""
    article = RSSAdapter("source", {"base_url": "https://example.test/feed"}).parse(payload)[0]
    assert article.url == "https://example.test/story"
    assert article.body == "Atom body"
    assert article.author == "Atom author"
    assert article.external_id == "atom-1"
    assert article.published_at is not None and article.published_at.year == 2025


def test_rss_adapter_bounds_ingestion_with_source_max_items() -> None:
    payload = "<rss><channel>" + "".join(
        f"<item><title>N{i}</title><link>https://example.test/{i}</link></item>"
        for i in range(5)
    ) + "</channel></rss>"
    articles = RSSAdapter("source", {"max_items": 3}).parse(payload)
    assert len(articles) == 3
    assert [article.title for article in articles] == ["N0", "N1", "N2"]


def test_crawler_prefers_body_txt_direct_text_over_page_controls() -> None:
    html = """
    <html><head><title>Site title</title></head><body>
      <section class="comp_view_news">
        <div class="title_area"><p class="date">Written: today</p><h1>Headline</h1></div>
        <div class="body_txt fr-view">
          <div class="img_box"><p class="cap no-print">Photo: source</p></div>
          First article paragraph.<br/><br/>
          Second article paragraph.
        </div>
      </section>
      <h2>Editor's Pick</h2><section class="comp_contents_3x"><p>Recommended</p></section>
    </body></html>
    """
    article = CrawlerAdapter(
        "source", CrawlerPolicyGuard("APPROVED", "APPROVED"), {"discover_links": False}
    ).parse({"url": "https://example.test/news/1", "html": html})[0]
    assert article.title == "Headline"
    assert article.body == "First article paragraph. Second article paragraph."
    assert "Written" not in article.body
    assert "Recommended" not in article.body
    assert "Photo" not in article.body


def test_crawler_reads_json_ld_and_discovers_index_links() -> None:
    html = """
    <script type="application/ld+json">
      {"@type":"NewsArticle","headline":"JSON headline","articleBody":"JSON body",
       "datePublished":"2025-02-03T00:00:00Z","author":{"name":"A Reporter"}}
    </script>
    <a href="/one">One story</a><a href="/two?utm_source=feed">Two story</a>
    """
    article = CrawlerAdapter(
        "source", CrawlerPolicyGuard("APPROVED", "APPROVED"), {"discover_links": False}
    ).parse({"url": "https://example.test/index", "html": html})[0]
    assert article.title == "JSON headline"
    assert article.body == "JSON body"
    assert article.author == "A Reporter"
    links = CrawlerAdapter(
        "source", CrawlerPolicyGuard("APPROVED", "APPROVED"), {"max_links": 1}
    ).parse({"url": "https://example.test/index", "html": '<a href="/one">One story</a>'})
    assert links[0].url == "https://example.test/one"
    assert links[0].title == "One story"

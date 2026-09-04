"""Pure source adapters and fixture parsers for API, RSS and crawler input."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin
from xml.etree import ElementTree

from .canonical import canonicalize_url, content_hash, normalize_text, url_hash
from .policy import CrawlerPolicyError, CrawlerPolicyGuard


class AdapterType(str, Enum):
    API = "API"
    RSS = "RSS"
    CRAWLER = "CRAWLER"


@dataclass(frozen=True)
class ArticleCandidate:
    """Normalised article data before persistence."""

    url: str
    title: str
    body: str = ""
    author: str | None = None
    published_at: datetime | None = None
    source_id: str | None = None
    raw_payload: Any = None
    external_id: str | None = None
    adapter_type: AdapterType = AdapterType.API

    def __post_init__(self) -> None:
        object.__setattr__(self, "url", canonicalize_url(self.url))
        object.__setattr__(self, "title", normalize_text(self.title))
        object.__setattr__(self, "body", normalize_text(self.body))

    @property
    def canonical_url(self) -> str:
        return self.url

    @property
    def canonical_url_hash(self) -> bytes:
        return url_hash(self.url)

    @property
    def body_hash(self) -> bytes:
        return content_hash(self.body)

    @property
    def content_hash(self) -> bytes:
        return content_hash(f"{self.title}\n{self.body}")

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["adapter_type"] = self.adapter_type.value
        return data


class SourceAdapter(ABC):
    """Interface shared by API/RSS/crawler adapters.

    ``parse`` is deliberately synchronous and side-effect free.  Network
    fetching belongs to an outer worker and is not part of this contract.
    """

    adapter_type: AdapterType

    def __init__(
        self,
        source_id: str | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        self.source_id = source_id
        self.config = dict(config or {})

    @abstractmethod
    def parse(self, payload: Any) -> list[ArticleCandidate]:
        raise NotImplementedError

    def parse_fixture(self, payload: Any) -> list[ArticleCandidate]:
        return self.parse(payload)


class APIAdapter(SourceAdapter):
    adapter_type = AdapterType.API

    def __init__(
        self,
        source_id: str | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(source_id, config)
        fields = self.config.get("fields")
        self.fields = dict(fields) if isinstance(fields, Mapping) else {}

    def parse(self, payload: Any) -> list[ArticleCandidate]:
        if isinstance(payload, (bytes, bytearray)):
            payload = json.loads(payload)
        if isinstance(payload, str):
            payload = json.loads(payload)
        items = self._items(payload)
        if not isinstance(items, Iterable) or isinstance(items, (str, bytes, bytearray, Mapping)):
            raise ValueError("API payload must contain an article list")
        result: list[ArticleCandidate] = []
        for item in items:
            if not isinstance(item, Mapping):
                continue
            # JSON:API and a number of news APIs wrap the article under
            # ``attributes``.  Preserve the original object as raw payload
            # while using the merged view for field extraction.
            candidate_item = item
            attributes = item.get("attributes")
            if isinstance(attributes, Mapping):
                candidate_item = {**dict(attributes), **dict(item)}
                candidate_item.pop("attributes", None)
            result.append(self._candidate(candidate_item, raw_item=item))
        return _limit_items(result, self.config)

    def _items(self, payload: Any) -> Any:
        if not isinstance(payload, Mapping):
            return payload
        configured_path = self.config.get("items_path") or self.config.get("item_path")
        if configured_path:
            configured = _path_get(payload, configured_path)
            if configured is not None:
                return configured
        # Prefer an explicit article list at each common envelope level.  A
        # nested ``data`` mapping is common in REST and JSON:API responses.
        for key in ("items", "articles", "results", "entries", "records"):
            value = _mapping_value(payload, key)
            if isinstance(value, list):
                return value
        for key in ("data", "response", "result", "payload"):
            value = _mapping_value(payload, key)
            if isinstance(value, Mapping):
                nested = self._items(value)
                if nested is not value:
                    return nested
            elif isinstance(value, list):
                return value
        if any(_mapping_value(payload, key) not in (None, "") for key in ("url", "link", "title", "headline")):
            return [payload]
        return []

    def _candidate(
        self,
        item: Mapping[str, Any],
        *,
        raw_item: Mapping[str, Any] | None = None,
    ) -> ArticleCandidate:
        url = self._field(item, "url", "link", "canonical_url", "href")
        if not url:
            raise ValueError("API article is missing url")
        base_url = self.config.get("base_url") or self.config.get("url_base")
        if base_url and not _is_absolute_http_url(str(url)):
            url = urljoin(str(base_url), str(url))
        return ArticleCandidate(
            url=str(url),
            title=_string_value(self._field(item, "title", "headline", "name")),
            body=_string_value(
                self._field(item, "content", "body", "description", "summary", "text")
            ),
            author=_author_value(self._field(item, "author", "byline", "creator")),
            published_at=parse_datetime(
                self._field(item, "published_at", "published", "pubDate", "date", "datePublished")
            ),
            source_id=self.source_id,
            raw_payload=dict(raw_item if raw_item is not None else item),
            external_id=_as_optional_str(self._field(item, "id", "guid", "uuid")),
            adapter_type=self.adapter_type,
        )

    def _field(self, item: Mapping[str, Any], *names: str) -> Any:
        configured_names: list[str] = []
        for name in names:
            configured = self.fields.get(name)
            if isinstance(configured, str):
                configured_names.append(configured)
            elif isinstance(configured, (list, tuple)):
                configured_names.extend(str(value) for value in configured)
        for name in (*configured_names, *names):
            value = _path_get(item, name)
            if value not in (None, "", [], {}):
                return value
        return None


class RSSAdapter(SourceAdapter):
    adapter_type = AdapterType.RSS

    def __init__(
        self,
        source_id: str | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(source_id, config)

    def parse(self, payload: Any) -> list[ArticleCandidate]:
        if isinstance(payload, str):
            raw_payload: str | bytes = payload
        elif isinstance(payload, (bytes, bytearray)):
            # ElementTree honours an XML declaration only when it receives
            # bytes.  This matters for feeds encoded as ISO-8859-1/EUC-KR.
            raw_payload = bytes(payload)
        else:
            raise ValueError("RSS payload must be XML text or bytes")
        try:
            root = ElementTree.fromstring(raw_payload)
        except ElementTree.ParseError as exc:
            raise ValueError("invalid RSS/Atom fixture") from exc
        result: list[ArticleCandidate] = []
        seen: set[str] = set()
        feed_url = self.config.get("base_url") or self.config.get("url_base")
        # Local-name matching handles RSS namespaces and Atom feeds.  Child
        # text is collected recursively because Atom author/content and RSS
        # extension elements are often nested or wrapped in CDATA/HTML.
        for node in root.iter():
            if _local_name(node.tag) not in {"item", "entry"}:
                continue
            fields = self._fields(node)
            link = self._link(node, fields)
            if feed_url and link and not _is_absolute_http_url(link):
                link = urljoin(str(feed_url), link)
            if not link:
                continue
            try:
                canonical = canonicalize_url(link)
            except ValueError:
                continue
            if canonical in seen:
                continue
            seen.add(canonical)
            body = _first_nonempty(
                fields.get("encoded"),
                fields.get("content:encoded"),
                fields.get("content"),
                fields.get("description"),
                fields.get("summary"),
            )
            result.append(
                ArticleCandidate(
                    url=canonical,
                    title=fields.get("title", ""),
                    body=_html_to_text(body),
                    author=_author_value(
                        _first_nonempty(
                            fields.get("creator"), fields.get("dc:creator"), fields.get("author")
                        )
                    ),
                    published_at=parse_datetime(
                        _first_nonempty(
                            fields.get("pubdate"),
                            fields.get("published"),
                            fields.get("updated"),
                            fields.get("date"),
                        )
                    ),
                    source_id=self.source_id,
                    raw_payload=ElementTree.tostring(node, encoding="unicode"),
                    external_id=_first_nonempty(fields.get("guid"), fields.get("id")) or None,
                    adapter_type=self.adapter_type,
                )
            )
        return _limit_items(result, self.config)

    @staticmethod
    def _fields(node: ElementTree.Element) -> dict[str, str]:
        fields: dict[str, str] = {}
        for child in node.iter():
            if child is node:
                continue
            name = _local_name(child.tag)
            text = _element_text(child)
            if not text:
                continue
            # Keep the qualified alias for common RSS extensions while also
            # retaining the local name for namespace-agnostic feeds.
            fields.setdefault(name, text)
            if ":" in child.tag:
                fields.setdefault(child.tag.rsplit("}", 1)[-1].lower(), text)
            if name == "creator":
                fields.setdefault("dc:creator", text)
        return fields

    @staticmethod
    def _link(node: ElementTree.Element, fields: Mapping[str, str]) -> str:
        links = [child for child in node if _local_name(child.tag) == "link"]
        # Atom can provide self, enclosure and alternate links.  Prefer the
        # HTML alternate link, then any non-enclosure link, and finally text.
        for child in links:
            href = (child.attrib.get("href") or "").strip()
            rel = (child.attrib.get("rel") or "alternate").lower()
            media = (child.attrib.get("type") or "").lower()
            if href and rel in {"alternate", ""} and media in {"", "text/html", "application/xhtml+xml"}:
                return href
        for child in links:
            href = (child.attrib.get("href") or "").strip()
            if href and (child.attrib.get("rel") or "").lower() not in {"self", "enclosure"}:
                return href
        return fields.get("link", "")


class _FixtureHTMLParser(HTMLParser):
    """Small dependency-free article extractor for ordinary news HTML.

    It deliberately collects structural signals rather than trying to
    implement a browser DOM.  JSON-LD and semantic metadata are preferred,
    then article/main and common body containers, then paragraph blocks.  The
    parser is bounded by the fetcher before it is called and ignores scripts,
    navigation, advertisements and other boilerplate elements.
    """

    _SKIP_TAGS = frozenset(
        {"script", "style", "noscript", "template", "svg", "canvas", "nav", "header", "footer", "aside", "form"}
    )
    _CONTENT_WORDS = re.compile(
        r"(?:^|[-_])(?:content|article|story|entry|post|body|main|text|detail|news|prose)(?:[-_]|$)",
        re.I,
    )
    _BOILERPLATE_WORDS = re.compile(
        r"(?:comment|related|recommend|share|social|advert|promo|banner|newsletter|breadcrumb|nav|date|time|caption|cap|func)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.json_ld: list[str] = []
        self.base_href: str | None = None
        self._stack: list[tuple[str, dict[str, str], bool, int]] = []
        self._title_depth = 0
        self._skip_depth = 0
        self._script_depth = 0
        self._script_chunks: list[str] = []
        self._block_tag: str | None = None
        self._block_chunks: list[str] = []
        self._block_score = 0
        self._block_boilerplate = False
        self.blocks: list[tuple[int, str]] = []
        self.content_chunks: list[tuple[int, str]] = []
        self.headings: list[str] = []

    @property
    def in_content(self) -> bool:
        return any(item[2] for item in self._stack) and self._skip_depth == 0

    @property
    def content_score(self) -> int:
        if self._skip_depth:
            return 0
        return max((item[3] for item in self._stack), default=0)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_d = {str(k).lower(): str(v or "") for k, v in attrs}
        if tag == "meta":
            key = (attrs_d.get("property") or attrs_d.get("name") or attrs_d.get("itemprop") or "").lower()
            value = attrs_d.get("content", "").strip()
            if key and value:
                self.meta.setdefault(key, value)
            return
        if tag == "base" and attrs_d.get("href"):
            self.base_href = attrs_d["href"].strip()
        if tag == "link" and attrs_d.get("href"):
            rel = " ".join(attrs_d.get("rel", "").lower().split())
            self.links.append({"href": attrs_d["href"].strip(), "rel": rel, "text": ""})
        if tag == "a" and attrs_d.get("href"):
            self.links.append({"href": attrs_d["href"].strip(), "rel": "", "text": ""})
        is_json_ld = tag == "script" and "ld+json" in attrs_d.get("type", "").lower()
        if is_json_ld:
            self._script_depth += 1
            self._script_chunks = []
        if tag == "title":
            self._title_depth += 1
        skip = self._skip_depth > 0 or tag in self._SKIP_TAGS
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        marker = " ".join(
            value
            for value in (attrs_d.get("id", ""), attrs_d.get("class", ""), attrs_d.get("role", ""))
            if value
        )
        itemprop = attrs_d.get("itemprop", "").lower()
        boilerplate = bool(self._BOILERPLATE_WORDS.search(marker))
        container_score = _html_container_score(tag, marker, itemprop)
        is_content = (
            not boilerplate
            and (
                tag in {"article", "main"}
                or itemprop in {"articlebody", "headline", "text"}
                or bool(self._CONTENT_WORDS.search(marker))
            )
        )
        self._stack.append((tag, attrs_d, is_content and not skip, container_score if not skip else 0))
        if not skip and tag in {"p", "h1", "h2", "h3", "h4", "blockquote", "pre", "li"}:
            self._finish_block()
            self._block_tag = tag
            self._block_chunks = []
            score = 3 if tag == "p" else 1
            if self.in_content and not boilerplate:
                score += 3
            self._block_score = score
            self._block_boilerplate = boilerplate

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if tag == "script" and self._script_depth:
            value = "".join(self._script_chunks).strip()
            if value:
                self.json_ld.append(value)
            self._script_chunks = []
            self._script_depth -= 1
        if self._block_tag == tag:
            self._finish_block()
        # HTML in the wild is often imperfect.  Pop to the matching tag so a
        # missing </p> does not cause all subsequent page text to be treated
        # as article content.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                del self._stack[index:]
                break
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not data:
            return
        if self._script_depth:
            self._script_chunks.append(data)
            return
        if self._title_depth:
            self.title.append(data)
        if self._block_tag and self._skip_depth == 0:
            self._block_chunks.append(data)
        elif self.in_content:
            self.content_chunks.append((self.content_score, data))
        # Link text is captured in a separate lightweight way; it is only used
        # for discovered index links and never becomes article body content.
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == "a" and index < len(self._stack):
                href = self._stack[index][1].get("href", "")
                if href and self.links:
                    self.links[-1]["text"] = normalize_text(self.links[-1].get("text", "") + " " + data)
                break

    def _finish_block(self) -> None:
        if self._block_tag is not None:
            text = normalize_text(" ".join(self._block_chunks))
            if text:
                self.blocks.append((self._block_score, text))
                if self._block_tag == "h1":
                    self.headings.append(text)
        self._block_tag = None
        self._block_chunks = []
        self._block_score = 0
        self._block_boilerplate = False


class CrawlerAdapter(SourceAdapter):
    adapter_type = AdapterType.CRAWLER

    def __init__(
        self,
        source_id: str | None = None,
        policy: CrawlerPolicyGuard | None = None,
        config: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(source_id, config)
        if not isinstance(policy, CrawlerPolicyGuard):
            raise CrawlerPolicyError(
                "crawler adapter requires an explicit robots and terms policy guard"
            )
        self.policy = policy

    def parse(self, payload: Any) -> list[ArticleCandidate]:
        self.policy.check()
        if isinstance(payload, Mapping):
            url = _first(payload, "url", "canonical_url", "link")
            html = _first(payload, "html", "body", "content", "payload")
            if not url or not html:
                raise ValueError("crawler fixture mapping requires url and html")
            raw = (
                bytes(html).decode("utf-8", errors="replace")
                if isinstance(html, (bytes, bytearray))
                else str(html)
            )
        else:
            raise ValueError("crawler fixture must be a mapping with url and html")
        parser = _FixtureHTMLParser()
        parser.feed(raw)
        parser.close()
        json_article = _json_ld_article(parser.json_ld)
        base_url = parser.base_href or str(url)
        title = (
            _string_value(json_article.get("headline"))
            or parser.meta.get("og:title")
            or parser.meta.get("twitter:title")
            or parser.meta.get("headline")
            or (parser.headings[0] if parser.headings else "")
            or normalize_text("".join(parser.title))
        )
        body = _string_value(json_article.get("articleBody"))
        if not body:
            body = _select_html_body(parser.blocks, parser.content_chunks)
        if not body:
            body = _html_to_text(
                parser.meta.get("description") or parser.meta.get("og:description") or ""
            )
        canonical = (
            _string_value(json_article.get("url"))
            or parser.meta.get("og:url")
            or _canonical_link(parser.links)
            or str(url)
        )
        canonical = urljoin(base_url, canonical)
        author = _author_value(json_article.get("author")) or _author_value(
            parser.meta.get("author") or parser.meta.get("article:author")
        )
        published = (
            json_article.get("datePublished")
            or json_article.get("dateCreated")
            or parser.meta.get("article:published_time")
            or parser.meta.get("datepublished")
            or parser.meta.get("date")
        )
        candidate = ArticleCandidate(
            url=canonical,
            title=title,
            body=body,
            author=author or None,
            published_at=parse_datetime(published),
            source_id=self.source_id,
            raw_payload=raw,
            adapter_type=self.adapter_type,
        )
        if not _as_bool(self.config.get("discover_links"), default=True) or body:
            return [candidate]
        # A crawler source may point at a section/index page.  Return useful
        # link candidates when the page itself has no article body; the worker
        # can then enqueue/fetch those URLs without treating navigation as an
        # article.  Existing article pages still produce exactly one result.
        discovered = self.discover_links(
            {"url": str(url), "html": raw},
            parsed=parser,
        )
        if not discovered:
            return [candidate]
        return discovered

    def discover_links(
        self,
        payload: Mapping[str, Any],
        *,
        parsed: _FixtureHTMLParser | None = None,
    ) -> list[ArticleCandidate]:
        url = _first(payload, "url", "canonical_url", "link")
        html = _first(payload, "html", "body", "content", "payload")
        if not url or not html:
            return []
        parser = parsed or _FixtureHTMLParser()
        if parsed is None:
            parser.feed(str(html))
            parser.close()
        base_url = urljoin(str(url), parser.base_href or str(url))
        max_links = _positive_int(self.config.get("max_links"), default=50)
        allowed = self.config.get("allowed_domains") or self.config.get("domains")
        allowed_domains = {str(item).lower() for item in allowed} if isinstance(allowed, (list, tuple, set)) else None
        result: list[ArticleCandidate] = []
        seen: set[str] = set()
        for item in parser.links:
            href = item.get("href", "")
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urljoin(base_url, href)
            try:
                canonical = canonicalize_url(absolute)
            except ValueError:
                continue
            if canonical in seen or canonical == canonicalize_url(str(url)):
                continue
            host = canonical.split("/", 3)[2].lower()
            if allowed_domains and host not in allowed_domains:
                continue
            if _looks_like_asset(canonical):
                continue
            seen.add(canonical)
            link_title = normalize_text(item.get("text", "")) or canonical.rsplit("/", 1)[-1]
            result.append(
                ArticleCandidate(
                    url=canonical,
                    title=link_title,
                    source_id=self.source_id,
                    raw_payload=None,
                    adapter_type=self.adapter_type,
                )
            )
            if len(result) >= max_links:
                break
        return result


def parse_api_fixture(
    payload: Any,
    *,
    source_id: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[ArticleCandidate]:
    return APIAdapter(source_id, config).parse(payload)


def parse_rss_fixture(
    payload: Any,
    *,
    source_id: str | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[ArticleCandidate]:
    return RSSAdapter(source_id, config).parse(payload)


def parse_html_fixture(
    payload: Mapping[str, Any],
    *,
    source_id: str | None = None,
    policy: CrawlerPolicyGuard | None = None,
    config: Mapping[str, Any] | None = None,
) -> list[ArticleCandidate]:
    return CrawlerAdapter(source_id, policy, config).parse(payload)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, ""):
            return mapping[key]
    # API fixtures sometimes use camelCase.
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for key in keys:
        if key.lower() in lowered and lowered[key.lower()] not in (None, ""):
            return lowered[key.lower()]
    return None


def _mapping_value(mapping: Mapping[str, Any], key: str) -> Any:
    """Get a mapping value with case/camel-case tolerant lookup."""

    if key in mapping:
        return mapping[key]
    lowered = {str(name).lower(): value for name, value in mapping.items()}
    return lowered.get(key.lower())


def _path_get(value: Any, path: Any) -> Any:
    """Read a dotted or sequence path without making API fixtures rigid."""

    if isinstance(path, str):
        parts = [part for part in path.split(".") if part]
    elif isinstance(path, (list, tuple)):
        parts = [str(part) for part in path]
    else:
        return None
    current = value
    for part in parts:
        if isinstance(current, Mapping):
            current = _mapping_value(current, part)
        else:
            return None
    return current


def _string_value(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, Mapping):
        for key in ("name", "text", "value", "content", "html"):
            nested = _mapping_value(value, key)
            if nested not in (None, ""):
                return _string_value(nested)
        return ""
    if isinstance(value, (list, tuple, set)):
        return normalize_text(" ".join(_string_value(item) for item in value))
    return _html_to_text(str(value))


def _author_value(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, Mapping):
        for key in ("name", "text", "value", "url"):
            nested = _mapping_value(value, key)
            if nested not in (None, ""):
                return _author_value(nested)
        return None
    if isinstance(value, (list, tuple, set)):
        names = [_author_value(item) for item in value]
        joined = ", ".join(name for name in names if name)
        return joined or None
    text = _html_to_text(str(value))
    return text or None


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _is_absolute_http_url(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("http://") or lowered.startswith("https://")


def _element_text(element: ElementTree.Element) -> str:
    return normalize_text(" ".join(part for part in element.itertext() if part))


class _InlineTextParser(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._SKIP:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip == 0:
            self.parts.append(data)


def _html_to_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    if "<" not in text or ">" not in text:
        return normalize_text(unescape(text))
    parser = _InlineTextParser()
    parser.feed(text)
    parser.close()
    return normalize_text(unescape(" ".join(parser.parts)))


def _select_html_body(
    blocks: Iterable[tuple[int, str]],
    content_chunks: Iterable[tuple[int, str]] | None = None,
) -> str:
    values = list(blocks)
    direct_values = list(content_chunks or [])
    direct_scores = [score for score, _text in direct_values if score > 0]
    strongest_direct_score = max(direct_scores, default=0)
    direct = [
        normalize_text(text)
        for score, text in direct_values
        if score == strongest_direct_score and normalize_text(text)
    ]
    direct_text = normalize_text(" ".join(_dedupe_adjacent(direct)))
    if direct_text and strongest_direct_score >= 8:
        # Explicit body_txt/article-body containers are more trustworthy than
        # a surrounding news section's title/date/share controls.
        high = [text for score, text in values if score >= 5]
        selected = normalize_text(" ".join(_dedupe_adjacent(high)))
        if selected and selected not in direct_text and len(selected) < len(direct_text) // 2:
            return normalize_text(f"{direct_text} {selected}")
        return direct_text
    # A high-score block is inside an article/main or an explicitly named
    # article-body container.  Keep all such paragraphs in source order.
    high = [text for score, text in values if score >= 5]
    if high:
        selected = normalize_text(" ".join(_dedupe_adjacent(high)))
        if direct_text and direct_text not in selected:
            selected = normalize_text(f"{selected} {direct_text}")
        return selected
    paragraphs = [text for score, text in values if score >= 3]
    if paragraphs:
        selected = normalize_text(" ".join(_dedupe_adjacent(paragraphs)))
        if direct_text and direct_text not in selected:
            selected = normalize_text(f"{selected} {direct_text}")
        return selected
    return direct_text


def _html_container_score(tag: str, marker: str, itemprop: str) -> int:
    marker_lower = marker.lower()
    if itemprop in {"articlebody", "text"}:
        return 12
    if any(token in marker_lower for token in ("body_txt", "article-body", "article_body", "story-body", "story_body")):
        return 12
    if tag == "article" or itemprop == "headline":
        return 10
    if tag == "main" or any(token in marker_lower for token in ("article", "story", "entry", "post", "detail")):
        return 8
    if any(token in marker_lower for token in ("news", "body", "text", "prose")):
        return 6
    if "content" in marker_lower and "contents" not in marker_lower:
        return 4
    return 0


def _dedupe_adjacent(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if not value or (result and result[-1] == value):
            continue
        result.append(value)
    return result


def _json_ld_article(values: Iterable[str]) -> dict[str, Any]:
    def candidates(value: Any) -> Iterable[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            graph = value.get("@graph")
            if isinstance(graph, list):
                yield from candidates(graph)
            else:
                yield value
        elif isinstance(value, list):
            for item in value:
                yield from candidates(item)

    article_types = {"article", "newsarticle", "reportagenewsarticle", "blogposting", "liveblogposting"}
    for raw in values:
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for item in candidates(decoded):
            kind = item.get("@type", "")
            kinds = {str(kind).lower()} if isinstance(kind, str) else {str(v).lower() for v in kind}
            if kinds & article_types or item.get("articleBody") or item.get("headline"):
                result = dict(item)
                main = result.get("mainEntityOfPage")
                if not result.get("url") and isinstance(main, Mapping):
                    result["url"] = main.get("@id") or main.get("url")
                return result
    return {}


def _canonical_link(links: Iterable[Mapping[str, str]]) -> str | None:
    for item in links:
        rel = {part for part in item.get("rel", "").split() if part}
        if "canonical" in rel and item.get("href"):
            return item["href"]
    return None


def _looks_like_asset(url: str) -> bool:
    path = url.split("?", 1)[0].lower()
    return path.endswith(
        (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js", ".pdf", ".zip", ".mp4", ".mp3")
    )


def _positive_int(value: Any, *, default: int) -> int:
    try:
        candidate = int(value)
    except (TypeError, ValueError):
        return default
    return candidate if candidate > 0 else default


def _limit_items(items: list[ArticleCandidate], config: Mapping[str, Any]) -> list[ArticleCandidate]:
    raw_limit = config.get("max_items")
    if raw_limit in (None, ""):
        return items
    limit = _positive_int(raw_limit, default=0)
    return items if limit == 0 else items[:limit]


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _as_optional_str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, Mapping):
        value = _first(value, "date", "value", "published", "updated", "datePublished")
        if value in (None, ""):
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        # APIs disagree on seconds versus milliseconds.  Values beyond the
        # year-5138 seconds range are unambiguously epoch milliseconds.
        timestamp = float(value)
        if abs(timestamp) > 100_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        # RFC 822 is common in RSS; avoid importing email.utils on every parse.
        from email.utils import parsedate_to_datetime

        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

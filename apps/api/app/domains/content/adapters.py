"""Pure source adapters and fixture parsers for API, RSS and crawler input."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree

from .canonical import canonicalize_url, content_hash, normalize_text, url_hash
from .policy import CrawlerPolicyGuard


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

    def __init__(self, source_id: str | None = None) -> None:
        self.source_id = source_id

    @abstractmethod
    def parse(self, payload: Any) -> list[ArticleCandidate]:
        raise NotImplementedError

    def parse_fixture(self, payload: Any) -> list[ArticleCandidate]:
        return self.parse(payload)


class APIAdapter(SourceAdapter):
    adapter_type = AdapterType.API

    def parse(self, payload: Any) -> list[ArticleCandidate]:
        if isinstance(payload, (bytes, bytearray)):
            payload = json.loads(payload)
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(payload, Mapping):
            items = payload.get(
                "items", payload.get("articles", payload.get("results", payload.get("data")))
            )
            if items is None:
                items = (
                    [payload]
                    if any(k in payload for k in ("url", "link", "title", "headline"))
                    else []
                )
        else:
            items = payload
        if not isinstance(items, Iterable) or isinstance(items, (str, bytes, bytearray, Mapping)):
            raise ValueError("API payload must contain an article list")
        return [self._candidate(item) for item in items if isinstance(item, Mapping)]

    def _candidate(self, item: Mapping[str, Any]) -> ArticleCandidate:
        url = _first(item, "url", "link", "canonical_url", "href")
        if not url:
            raise ValueError("API article is missing url")
        return ArticleCandidate(
            url=str(url),
            title=str(_first(item, "title", "headline", "name") or ""),
            body=str(_first(item, "content", "body", "description", "summary", "text") or ""),
            author=_as_optional_str(_first(item, "author", "byline")),
            published_at=parse_datetime(
                _first(item, "published_at", "published", "pubDate", "date")
            ),
            source_id=self.source_id,
            raw_payload=dict(item),
            external_id=_as_optional_str(_first(item, "id", "guid", "uuid")),
            adapter_type=self.adapter_type,
        )


class RSSAdapter(SourceAdapter):
    adapter_type = AdapterType.RSS

    def parse(self, payload: Any) -> list[ArticleCandidate]:
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8", errors="replace")
        if not isinstance(payload, str):
            raise ValueError("RSS payload must be XML text or bytes")
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError as exc:
            raise ValueError("invalid RSS/Atom fixture") from exc
        result: list[ArticleCandidate] = []
        # Local-name matching handles RSS namespaces and Atom feeds.
        for node in root.iter():
            if _local_name(node.tag) not in {"item", "entry"}:
                continue
            fields = {_local_name(child.tag): (child.text or "").strip() for child in node}
            link = fields.get("link", "")
            for child in node:
                if _local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    break
            if not link:
                continue
            result.append(
                ArticleCandidate(
                    url=link,
                    title=fields.get("title", ""),
                    body=fields.get(
                        "encoded",
                        fields.get("description", fields.get("summary", fields.get("content", ""))),
                    ),
                    author=fields.get("creator", fields.get("author")) or None,
                    published_at=parse_datetime(
                        fields.get("pubDate", fields.get("published", fields.get("updated")))
                    ),
                    source_id=self.source_id,
                    raw_payload=ElementTree.tostring(node, encoding="unicode"),
                    external_id=fields.get("guid", fields.get("id")) or None,
                    adapter_type=self.adapter_type,
                )
            )
        return result


class _FixtureHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.body: list[str] = []
        self.meta: dict[str, str] = {}
        self._in_title = False
        self._in_article = False
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k.lower(): v or "" for k, v in attrs}
        tag = tag.lower()
        if tag == "meta":
            key = attrs_d.get("property") or attrs_d.get("name")
            if key and attrs_d.get("content"):
                self.meta[key.lower()] = attrs_d["content"]
        if tag == "title":
            self._in_title = True
        if tag in {"article", "main"} or attrs_d.get("itemprop") in {"articleBody", "headline"}:
            self._in_article = True
            self._depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in {"article", "main"} and self._depth:
            self._depth -= 1
            if not self._depth:
                self._in_article = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title.append(data)
        if self._in_article or not self.body:
            self.body.append(data)


class CrawlerAdapter(SourceAdapter):
    adapter_type = AdapterType.CRAWLER

    def __init__(
        self, source_id: str | None = None, policy: CrawlerPolicyGuard | None = None
    ) -> None:
        super().__init__(source_id)
        self.policy = policy

    def parse(self, payload: Any) -> list[ArticleCandidate]:
        if self.policy is not None:
            self.policy.check()
        if isinstance(payload, Mapping):
            url = _first(payload, "url", "canonical_url", "link")
            html = _first(payload, "html", "body", "content", "payload")
            if not url or not html:
                raise ValueError("crawler fixture mapping requires url and html")
            raw = str(html)
        else:
            raise ValueError("crawler fixture must be a mapping with url and html")
        parser = _FixtureHTMLParser()
        parser.feed(raw)
        title = (
            parser.meta.get("og:title")
            or parser.meta.get("twitter:title")
            or normalize_text("".join(parser.title))
        )
        text = parser.meta.get("description") or normalize_text(" ".join(parser.body))
        canonical = parser.meta.get("og:url") or str(url)
        author = parser.meta.get("author") or parser.meta.get("article:author")
        published = parser.meta.get("article:published_time") or parser.meta.get("date")
        return [
            ArticleCandidate(
                url=canonical,
                title=title,
                body=text,
                author=author or None,
                published_at=parse_datetime(published),
                source_id=self.source_id,
                raw_payload=raw,
                adapter_type=self.adapter_type,
            )
        ]


def parse_api_fixture(payload: Any, *, source_id: str | None = None) -> list[ArticleCandidate]:
    return APIAdapter(source_id).parse(payload)


def parse_rss_fixture(payload: Any, *, source_id: str | None = None) -> list[ArticleCandidate]:
    return RSSAdapter(source_id).parse(payload)


def parse_html_fixture(
    payload: Mapping[str, Any],
    *,
    source_id: str | None = None,
    policy: CrawlerPolicyGuard | None = None,
) -> list[ArticleCandidate]:
    return CrawlerAdapter(source_id, policy).parse(payload)


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


def _as_optional_str(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def parse_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=UTC)
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

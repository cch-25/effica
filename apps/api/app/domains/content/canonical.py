"""Deterministic URL and text canonicalisation helpers."""

from __future__ import annotations

import hashlib
import posixpath
import re
import unicodedata
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

# Common analytics/campaign keys are not part of a resource identity.  The
# allow-list approach for all other keys avoids accidentally dropping a
# meaningful query parameter (for example a page or article id).
_TRACKING_KEYS = {
    "_hsenc",
    "_hsmi",
    "cmpid",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "s_cid",
    "share",
    "si",
}
_TRACKING_PREFIXES = ("utm_", "pk_", "mtm_")
_WS_RE = re.compile(r"\s+")


def _normalise_percent(value: str, *, safe: str = "") -> str:
    """Decode only unreserved percent escapes, then quote canonically."""

    # Reserved escapes (notably ``%2F``) must not be silently changed into a
    # path separator.  Keep them escaped while normalising hex case; decode
    # only RFC 3986 unreserved characters.
    def replace(match: re.Match[str]) -> str:
        character = chr(int(match.group(1), 16))
        if character.isascii() and (character.isalnum() or character in "-._~"):
            return character
        return "%" + match.group(1).upper()

    escaped = re.sub(r"%([0-9A-Fa-f]{2})", replace, value)
    return quote(escaped, safe=safe + "-._~%")


def canonicalize_url(url: str) -> str:
    """Return a stable identity URL.

    Only HTTP(S) URLs are accepted.  Hostnames are lower-cased/IDNA encoded,
    default ports and fragments are removed, path escapes are normalised, and
    well-known tracking query parameters are dropped.  Query pairs are sorted
    while retaining duplicate values.
    """

    if not isinstance(url, str) or not url.strip():
        raise ValueError("url must be a non-empty string")
    raw = url.strip()
    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are supported")
    if not parts.hostname:
        raise ValueError("URL must include a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("userinfo in URL is not supported")
    try:
        host = parts.hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ValueError("invalid URL hostname") from exc
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid URL port") from exc
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    if ":" in host and not host.startswith("[") and parts.hostname.count(":") > 0:
        host = f"[{host}]"

    path = _normalise_percent(parts.path or "/", safe="/:@!$&'()*+,;=")
    # Resolve dot segments and use one spelling for a resource's trailing
    # slash.  The root slash is retained because an empty path and ``/`` are
    # equivalent in HTTP URLs.
    path = posixpath.normpath(path)
    if not path.startswith("/"):
        path = "/" + path
    if path != "/":
        path = path.rstrip("/")
    pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in _TRACKING_KEYS or key_lower.startswith(_TRACKING_PREFIXES):
            continue
        # ``parse_qsl`` has already decoded one layer of percent escapes and
        # translated ``+`` to a space. Quote the decoded components exactly
        # once; passing pre-escaped values through ``urlencode`` would turn
        # ``%20`` into ``%2520`` and change the resource identity.
        pairs.append((key, value))
    pairs.sort()
    query = "&".join(
        f"{quote(str(key), safe='-._~')}={quote(str(value), safe='-._~')}"
        for key, value in pairs
    )
    return urlunsplit((scheme, host, path, query, ""))


def url_hash(url: str) -> bytes:
    """SHA-256 digest of :func:`canonicalize_url` as 32 raw bytes."""

    return hashlib.sha256(canonicalize_url(url).encode("utf-8")).digest()


def normalize_text(text: str | None) -> str:
    """Unicode-normalise and collapse whitespace for content identity."""

    if text is None:
        return ""
    value = unicodedata.normalize("NFKC", str(text)).replace("\u00a0", " ")
    return _WS_RE.sub(" ", value).strip()


def content_hash(text: str | None) -> bytes:
    """SHA-256 digest of normalised article text."""

    return hashlib.sha256(normalize_text(text).encode("utf-8")).digest()


# Friendly aliases used by workers and tests.
canonical_url = canonicalize_url
hash_url = url_hash
canonical_url_hash = url_hash
compute_content_hash = content_hash

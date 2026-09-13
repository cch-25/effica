"""Conservative detection of publisher controls accidentally collected as news.

Match complete labels or runs of labels, never keywords within reporting. This
also handles legacy bodies where HTML extraction flattened a toolbar into text.
"""

from __future__ import annotations

import re
from html import unescape

_TIMESTAMP = (
    r"(?:등록|입력|수정|최종\s*수정|기사입력|기사수정)\s*[:：]?\s*"
    r"\d{4}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}\.?"
    r"(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?"
)
_PREFERRED_SOURCE = r"(?:구글|Google)(?:에서|의)?\s*선호하는\s*매체로\s*추가"
_LABEL = (
    rf"(?:{_TIMESTAMP}|{_PREFERRED_SOURCE}|"
    r"글자\s*크기\s*(?:조절|설정|확대|축소)|"
    r"폰트\s*크기\s*(?:조절|설정)|글씨\s*(?:크게|작게)|"
    r"크게|작게|확대|축소|공유하기|기사\s*공유|인쇄하기|기사\s*인쇄|"
    r"URL\s*복사|링크\s*복사|주소\s*복사|스크랩|구독하기)"
)
_RUN = re.compile(rf"{_LABEL}(?:(?:\s+|\s*[|/]\s*){_LABEL})*", re.I)
_LABEL_RE = re.compile(_LABEL, re.I)
_STRONG = re.compile(
    rf"{_TIMESTAMP}|{_PREFERRED_SOURCE}|(?:작게\s+크게|크게\s+작게)", re.I
)


def is_article_boilerplate(text: str) -> bool:
    """Whether the entire text consists of known publisher UI labels."""
    value = " ".join(unescape(text).split())
    return bool(value and _RUN.fullmatch(value))


def strip_article_boilerplate(text: str) -> str:
    """Remove UI-only lines and distinctive flattened prefixes.

    Generic labels such as '크게' alone never strip the start of a sentence.
    A label quoted or discussed in a sentence is retained as article content.
    """
    lines: list[str] = []
    for line in unescape(text).splitlines():
        value = line.strip()
        if is_article_boilerplate(value):
            continue
        prefix = _RUN.match(value)
        if (
            prefix
            and prefix.end() < len(value)
            and value[prefix.end()].isspace()
            and _STRONG.search(prefix.group())
            and len(_LABEL_RE.findall(prefix.group())) >= 2
        ):
            value = value[prefix.end():].lstrip()
        lines.append(value)
    return "\n".join(lines)


def evidence_contains_boilerplate(quote: str) -> bool:
    """Reject contaminated quotes whole, preserving offsets of accepted ones."""
    return " ".join(strip_article_boilerplate(quote).split()) != " ".join(unescape(quote).split())

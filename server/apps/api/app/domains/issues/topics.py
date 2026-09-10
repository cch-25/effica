"""The public taxonomy is restricted to political policy debates."""
from __future__ import annotations

import hashlib

PUBLIC_ISSUE_TOPICS = ("정치", "경제", "사회")

_TOPIC_ALIASES = (
    ("정치", ("정치", "정책", "정부", "국회", "외교", "안보", "국제")),
    ("경제", ("경제", "금융", "부동산", "주거", "고용", "통상")),
    ("사회", ("사회", "교육", "보건", "복지", "환경", "노동")),
)
_TOPIC_KEYWORDS = (
    ("경제", ("경제", "금융", "금리", "재정", "세금", "물가", "부동산", "주택", "관세", "무역")),
    ("정치", ("정치", "대통령", "국회", "정당", "선거", "총선", "대선", "입법", "외교", "안보", "북한")),
    ("사회", ("사회", "교육", "복지", "보건", "의료", "노동", "환경", "기후", "차별", "인권")),
)


def infer_issue_topic(title: str, summary: str = "") -> str:
    haystack = f"{title} {summary}".casefold()
    for topic, keywords in _TOPIC_KEYWORDS:
        if any(keyword in haystack for keyword in keywords):
            return topic
    return ""


def normalize_issue_topic(topic: str | None, title: str, summary: str = "") -> str:
    normalized = (topic or "").strip()
    if normalized in PUBLIC_ISSUE_TOPICS:
        return normalized
    for public_topic, aliases in _TOPIC_ALIASES:
        if any(alias in normalized.casefold() for alias in aliases):
            return public_topic
    return infer_issue_topic(title, summary)


def canonical_topic_editorial_key(topic: str) -> str:
    if topic not in PUBLIC_ISSUE_TOPICS:
        raise ValueError(f"unsupported public issue topic: {topic}")
    return f"public-topic:{topic}"


def canonical_topic_issue_id(topic: str) -> str:
    value = canonical_topic_editorial_key(topic)
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    number = int.from_bytes(digest[:16], "big")
    chars = [alphabet[0]] * 26
    for index in range(25, -1, -1):
        chars[index] = alphabet[number & 31]
        number >>= 5
    return "".join(chars)

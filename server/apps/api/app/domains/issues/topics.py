"""Canonical public issue topics and conservative title-based fallback classification."""

from __future__ import annotations

import hashlib

PUBLIC_ISSUE_TOPICS = ("정치", "사회", "경제", "국제", "산업", "문화", "스포츠", "기타")

_TOPIC_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("정치", ("정치", "정책", "정부", "국회")),
    ("국제", ("국제", "외교", "안보", "세계")),
    ("사회", ("사회", "교육", "보건", "복지", "환경")),
    ("경제", ("경제", "금융", "부동산", "주거", "고용")),
    ("산업", ("산업", "과학", "기술", "it", "테크")),
    ("문화", ("문화", "연예", "방송", "공연", "예술")),
    ("스포츠", ("스포츠", "체육", "축구", "야구", "농구")),
)

_TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "국제",
        (
            "국제",
            "외교",
            "안보",
            "북한",
            "한미",
            "한일",
            "우크라이나",
            "통상",
            "관세",
            "무역",
            "공급망",
        ),
    ),
    (
        "산업",
        (
            "산업",
            "인공지능",
            "ai",
            "반도체",
            "디지털",
            "로봇",
            "바이오",
            "자동차",
            "조선",
            "에너지",
            "기술",
            "연구개발",
            "우주",
            "이차전지",
            "제조",
        ),
    ),
    (
        "스포츠",
        (
            "스포츠",
            "체육",
            "축구",
            "야구",
            "농구",
            "배구",
            "골프",
            "올림픽",
            "선수",
            "리그",
            "kbo",
            "fifa",
            "월드컵",
        ),
    ),
    (
        "문화",
        (
            "문화",
            "영화",
            "드라마",
            "음악",
            "가수",
            "배우",
            "연예",
            "공연",
            "미술",
            "전시",
            "방송",
            "예능",
            "작가",
        ),
    ),
    (
        "경제",
        (
            "경제",
            "금융",
            "금리",
            "재정",
            "세금",
            "물가",
            "부동산",
            "주택",
            "고용",
            "중소기업",
        ),
    ),
    (
        "정치",
        ("정치", "대통령", "국회", "정당", "선거", "총선", "대선", "입법"),
    ),
    (
        "사회",
        (
            "사회",
            "교육",
            "학교",
            "재난",
            "화재",
            "범죄",
            "경찰",
            "복지",
            "아동",
            "청년",
            "보건",
            "의료",
            "노동",
            "환경",
            "기후",
            "교통",
        ),
    ),
)


def infer_issue_topic(title: str, summary: str = "") -> str:
    """Return a broad public topic without pretending uncertain matches are exact."""

    haystack = f"{title} {summary}".casefold()
    for topic, keywords in _TOPIC_KEYWORDS:
        if any(keyword.casefold() in haystack for keyword in keywords):
            return topic
    return "기타"


def normalize_issue_topic(topic: str | None, title: str, summary: str = "") -> str:
    """Collapse legacy/editorial labels into the stable public navigation taxonomy."""

    normalized = (topic or "").strip()
    if normalized in PUBLIC_ISSUE_TOPICS:
        return normalized
    folded = normalized.casefold()
    for public_topic, aliases in _TOPIC_ALIASES:
        if any(alias.casefold() in folded for alias in aliases):
            return public_topic
    return infer_issue_topic(title, summary)


def canonical_topic_editorial_key(topic: str) -> str:
    """Return the unique editorial key used by one durable public topic bucket."""

    if topic not in PUBLIC_ISSUE_TOPICS:
        raise ValueError(f"unsupported public issue topic: {topic}")
    return f"public-topic:{topic}"


def canonical_topic_issue_id(topic: str) -> str:
    """Return a deterministic ULID-shaped id shared by recovery and workers."""

    value = canonical_topic_editorial_key(topic)
    digest = hashlib.sha256(value.encode("utf-8")).digest()
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    number = int.from_bytes(digest[:16], "big")
    chars = [alphabet[0]] * 26
    for index in range(25, -1, -1):
        chars[index] = alphabet[number & 31]
        number >>= 5
    return "".join(chars)

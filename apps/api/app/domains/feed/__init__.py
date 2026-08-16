"""Deterministic diversity-aware feed ranking."""

from .ranking import (
    FeedCandidate,
    RankedFeedItem,
    generate_candidates,
    rank_feed,
    reason_code_for,
)

__all__ = ["FeedCandidate", "RankedFeedItem", "generate_candidates", "rank_feed", "reason_code_for"]

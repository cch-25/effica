"""Display interpretation of the existing beta questionnaire coordinates.

Economy alone determines left/right. Civil liberty and internationalism stay
independent. The inclusive center band is a display rule, not a validated cutoff.
Keep client/features/share-cards/ideology-model.ts in agreement.
"""

from __future__ import annotations

import math

IDEOLOGY_CENTER_BAND = 10


def interpret_ideology(x: float, y: float, z: float) -> dict[str, str]:
    if not all(math.isfinite(value) and -100 <= value <= 100 for value in (x, y, z)):
        raise ValueError("ideology coordinates must be finite and in [-100,100]")

    def band(value: float, negative: str, neutral: str, positive: str) -> str:
        if value < -IDEOLOGY_CENTER_BAND:
            return negative
        if value > IDEOLOGY_CENTER_BAND:
            return positive
        return neutral

    economic = band(x, "좌파", "중도", "우파")
    authority = band(y, "권위주의", "혼합", "자유주의")
    international = band(z, "주권주의", "혼합", "국제주의")
    prefix = "" if authority == "혼합" else f"{authority} "
    return {
        "economic": economic,
        "authority": authority,
        "international": international,
        "label": f"{prefix}{economic} 성향",
    }

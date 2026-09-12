"""Korean share image for consumption diversity and questionnaire-only ideology."""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from apps.api.app.domains.sharing.ideology import interpret_ideology

FONT_DIR = Path(__file__).resolve().parents[1] / "assets"


def _font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    name = "ChosunBoldMyungjo.ttf" if weight >= 600 else "ChosunShinMyungjo.ttf"
    font = ImageFont.truetype(str(FONT_DIR / name), size)
    return font


def render_consumption_card(public: Mapping[str, Any]) -> bytes:
    image = Image.new("RGB", (1200, 1000), "#FFFFFF")
    draw = ImageDraw.Draw(image)
    ink, muted, line = "#242424", "#595959", "#BDBDBD"
    font = _font(36, 600)
    body = _font(25)
    small = _font(22)
    draw.line((70, 30, 1130, 30), fill=ink, width=1)
    draw.text((70, 48), "에피카", font=_font(46), fill=ink)
    draw.text((1130, 64), "EFFICA / 독자 기록", font=small, fill=ink, anchor="ra")
    draw.line((70, 110, 1130, 110), fill=ink, width=2)
    draw.line((70, 116, 1130, 116), fill=ink, width=1)
    draw.text((70, 136), "나의 뉴스 소비 성향", font=font, fill=ink)
    name = str(public.get("display_name") or "")[:40]
    name_font = body
    for size in range(25, 15, -1):
        name_font = _font(size)
        if draw.textlength(name, font=name_font) <= 1040:
            break
    draw.text((1130, 185), name, font=name_font, fill=muted, anchor="ra")
    snapshot = public["snapshot"]
    ideology = snapshot.get("ideology")
    if not isinstance(ideology, Mapping) or "diversity_score" not in snapshot:
        draw.text((70, 280), "이전 방식으로 만든 카드입니다.", font=font, fill=ink)
        draw.text((70, 350), "기사 평가는 이용자의 정치성향을 뜻하지 않습니다.", font=body, fill=muted)
        draw.text((70, 400), "새 카드를 만들어 뉴스 소비 다양성과 검사 결과를 확인해 주세요.", font=body, fill=muted)
    else:
        score = max(0, min(100, int(snapshot["diversity_score"])))
        count = int(snapshot.get("diversity_article_count", 0))
        draw.line((70, 220, 1130, 220), fill=line, width=2)
        draw.text((70, 245), "다양성", font=body, fill=ink)
        draw.text((1130, 245), f"{score}/100", font=body, fill=ink, anchor="ra")
        draw.line((80, 310, 1120, 310), fill="#BDBDBD", width=5)
        marker = 80 + 1040 * score / 100
        draw.ellipse((marker - 9, 301, marker + 9, 319), fill="#404040")
        draw.text((70, 335), "0 낮음 / 단일 성향의 뉴스 위주 소비", font=small, fill=muted)
        draw.text((1130, 335), "100 높음 / 다양한 성향의 뉴스 균형 소비", font=small, fill=muted, anchor="ra")
        draw.text((70, 378), f"공개 분석이 있는 소비 기사 {count}개 기준" if count else "아직 점수에 반영할 기사 기록이 없습니다.", font=small, fill=muted)
        draw.line((70, 438, 1130, 438), fill=line, width=2)
        draw.text((70, 458), "3차원 이념 위치", font=body, fill=ink)

        def project(x: float, y: float, z: float) -> tuple[float, float]:
            # Positive y means civil liberty: below authority, as on the web map.
            return (380 + x * 1.45 + z * .55, 690 + y * 1.1 - z * .35)

        for a in (-100, 100):
            for b in (-100, 100):
                for edge in ((project(-100, a, b), project(100, a, b)), (project(a, -100, b), project(a, 100, b)), (project(a, b, -100), project(a, b, 100))):
                    draw.line(edge, fill=line, width=1)
        for edge, color in (([project(-100, 0, 0), project(100, 0, 0)], "#303030"), ([project(0, -100, 0), project(0, 100, 0)], "#5A5A5A"), ([project(0, 0, -100), project(0, 0, 100)], "#404040")):
            draw.line(edge, fill=color, width=3)
        for xy, text, color in (((190, 690), "좌파", "#303030"), ((572, 690), "우파", "#303030"), ((380, 535), "권위주의", "#5A5A5A"), ((380, 856), "자유주의", "#5A5A5A"), ((485, 628), "국제주의", "#404040"), ((270, 757), "주권주의", "#404040")):
            draw.text(xy, text, font=small, fill=color, anchor="mm")
        completed = ideology.get("completed") is True
        coords = [max(-100, min(100, int(ideology.get(axis, 0)))) if completed else 0 for axis in ("x", "y", "z")]
        if completed:
            result = interpret_ideology(*coords)
            px, py = project(*coords)
            draw.ellipse((px - 9, py - 9, px + 9, py + 9), fill=ink, outline="white", width=2)
            draw.text((720, 540), result["label"], font=_font(28, 600), fill=ink)
            for i, (label, key, value) in enumerate(zip(("좌우", "권위 / 자유", "국제관"), ("economic", "authority", "international"), coords, strict=True)):
                draw.text((720, 604 + i * 62), f"{label}: {result[key]} {value:+d}", font=small, fill=ink)
            draw.text((720, 808), "좌우는 경제정책 응답 기준", font=small, fill=muted)
            draw.text((720, 842), "기사 평가는 반영하지 않습니다.", font=small, fill=muted)
        else:
            draw.text((760, 595), "검사 미실시", font=body, fill=ink)
            draw.text((760, 653), "기본 좌표 (0,0,0)", font=body, fill=ink)
            draw.text((760, 728), "아직 측정하지 않았으며", font=small, fill=muted)
            draw.text((760, 763), "중도를 뜻하지 않습니다.", font=small, fill=muted)
        draw.text((70, 931), "카드를 만든 시점의 기록입니다. 이념 검사는 정식 검증 전인 베타 참고 자료입니다.", font=small, fill=muted)
    draw.line((70, 910, 1130, 910), fill=line, width=1)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

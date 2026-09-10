"""Korean share image for consumption diversity and questionnaire-only ideology."""

from __future__ import annotations

import io
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parents[1] / "assets" / "NotoSansKR.ttf"


def _font(size: int, weight: int = 400) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(FONT), size)
    font.set_variation_by_axes([weight])
    return font


def render_consumption_card(public: Mapping[str, Any]) -> bytes:
    image = Image.new("RGB", (1200, 1000), "#FFFAF0")
    draw = ImageDraw.Draw(image)
    ink, muted, line = "#202735", "#5B6472", "#D6D2C9"
    font = _font(36, 600)
    body = _font(25)
    small = _font(22)
    draw.text((70, 45), "EFFICA / 뉴스 소비 기록", font=small, fill=muted)
    draw.text((70, 98), "나의 뉴스 소비 성향", font=font, fill=ink)
    name = str(public.get("display_name") or "")[:40]
    name_font = body
    for size in range(25, 15, -1):
        name_font = _font(size)
        if draw.textlength(name, font=name_font) <= 1040:
            break
    draw.text((70, 155), name, font=name_font, fill=muted)
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
        draw.line((80, 310, 1120, 310), fill="#CDD7EF", width=5)
        marker = 80 + 1040 * score / 100
        draw.ellipse((marker - 9, 301, marker + 9, 319), fill="#3657A6")
        draw.text((70, 335), "0 낮음 / 단일 성향의 뉴스 위주 소비", font=small, fill=muted)
        draw.text((1130, 335), "100 높음 / 다양한 성향의 뉴스 균형 소비", font=small, fill=muted, anchor="ra")
        draw.text((70, 378), f"공개 분석이 있는 소비 기사 {count}개 기준" if count else "아직 점수에 반영할 기사 기록이 없습니다.", font=small, fill=muted)
        draw.line((70, 438, 1130, 438), fill=line, width=2)
        draw.text((70, 458), "3차원 이념 위치", font=body, fill=ink)

        def project(x: float, y: float, z: float) -> tuple[float, float]:
            return (390 + x * 1.5 + y * .9, 690 + x * .35 - y * .6 - z * 1.15)

        for a in (-65, 65):
            for b in (-65, 65):
                for edge in ((project(-65, a, b), project(65, a, b)), (project(a, -65, b), project(a, 65, b)), (project(a, b, -65), project(a, b, 65))):
                    draw.line(edge, fill=line, width=1)
        for edge, color in (([project(-115, 0, 0), project(115, 0, 0)], "#A14443"), ([project(0, -115, 0), project(0, 115, 0)], "#28704E"), ([project(0, 0, -105), project(0, 0, 115)], "#3657A6")):
            draw.line(edge, fill=color, width=3)
        for xy, text, color in (((175, 638), "경제적 좌", "#A14443"), ((602, 731), "경제적 우", "#A14443"), ((230, 781), "권위주의", "#28704E"), ((557, 595), "자유주의", "#28704E"), ((390, 520), "국제주의 / 세계주의", "#3657A6"), ((390, 842), "민족주의 / 주권주의", "#3657A6")):
            draw.text(xy, text, font=small, fill=color, anchor="mm")
        completed = ideology.get("completed") is True
        coords = [max(-100, min(100, int(ideology.get(axis, 0)))) if completed else 0 for axis in ("x", "y", "z")]
        px, py = project(*coords)
        draw.ellipse((px - 9, py - 9, px + 9, py + 9), fill=ink, outline="white", width=2)
        if completed:
            draw.text((760, 555), "검사 응답 기준 / 베타", font=body, fill=ink)
            for i, (label, value) in enumerate(zip(("경제 (X)", "사회문화 (Y)", "국제 (Z)"), coords, strict=True)):
                draw.text((760, 620 + i * 62), f"{label}   {value:+d}", font=body, fill=ink)
            draw.text((760, 820), "기사 평가는 좌표에", font=small, fill=muted)
            draw.text((760, 854), "반영되지 않습니다.", font=small, fill=muted)
        else:
            draw.text((760, 595), "검사 미실시", font=body, fill=ink)
            draw.text((760, 653), "기본 좌표 (0,0,0)", font=body, fill=ink)
            draw.text((760, 728), "아직 측정하지 않았으며", font=small, fill=muted)
            draw.text((760, 763), "중도를 뜻하지 않습니다.", font=small, fill=muted)
        draw.text((70, 931), "카드를 만든 시점의 기록입니다. 이념 검사는 정식 검증 전인 베타 참고 자료입니다.", font=small, fill=muted)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()

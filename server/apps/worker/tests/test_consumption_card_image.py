from __future__ import annotations

import io

from PIL import Image

from apps.worker.worker.handlers.consumption_card_image import render_consumption_card


def test_card_exports_korean_diversity_and_separate_ideology(tmp_path):
    for completed in (False, True):
        png = render_consumption_card({
            "display_name": "곽아영",
            "snapshot": {
                "diversity_score": 68,
                "diversity_article_count": 12,
                "ideology": {"completed": completed, "x": 28, "y": 12, "z": 35},
            },
        })
        image = Image.open(io.BytesIO(png))
        assert image.size == (1200, 1000)
        assert image.getbbox() == (0, 0, 1200, 1000)
        assert len(png) > 20_000
        (tmp_path / f"consumption-{completed}.png").write_bytes(png)


def test_legacy_card_does_not_render_inferred_political_position(monkeypatch):
    from apps.worker.worker.handlers import consumption_card_image as renderer

    texts = []
    original = renderer.ImageDraw.ImageDraw.text

    def capture(self, xy, text, *args, **kwargs):
        texts.append(text)
        return original(self, xy, text, *args, **kwargs)

    monkeypatch.setattr(renderer.ImageDraw.ImageDraw, "text", capture)
    render_consumption_card({"snapshot": {"x": -90, "sensationalism": 95}})
    assert "이전 방식으로 만든 카드입니다." in texts
    assert not any("-90" in text or "95" in text for text in texts)


def test_export_uses_the_same_ideology_axes_and_interpretation(monkeypatch):
    from apps.worker.worker.handlers import consumption_card_image as renderer

    texts = []
    markers = []
    original_text = renderer.ImageDraw.ImageDraw.text
    original_ellipse = renderer.ImageDraw.ImageDraw.ellipse

    def capture_text(self, xy, text, *args, **kwargs):
        texts.append((xy, text))
        return original_text(self, xy, text, *args, **kwargs)

    def capture_marker(self, xy, *args, **kwargs):
        markers.append(xy)
        return original_ellipse(self, xy, *args, **kwargs)

    monkeypatch.setattr(renderer.ImageDraw.ImageDraw, "text", capture_text)
    monkeypatch.setattr(renderer.ImageDraw.ImageDraw, "ellipse", capture_marker)
    snapshot = {"diversity_score": 68, "ideology": {"completed": True, "x": -80, "y": 60, "z": 0}}
    render_consumption_card({"snapshot": snapshot})
    positions = {text: xy for xy, text in texts}
    assert "자유주의 좌파 성향" in positions
    assert positions["좌파"][0] < positions["우파"][0]
    assert positions["권위주의"][1] < positions["자유주의"][1]
    # The user's point is left of the authority/liberty axis and below the left/right axis.
    point = markers[-1]
    assert (point[0] + point[2]) / 2 < positions["권위주의"][0]
    assert (point[1] + point[3]) / 2 > positions["좌파"][1]

    texts.clear()
    markers.clear()
    snapshot["ideology"]["completed"] = False
    render_consumption_card({"snapshot": snapshot})
    assert len(markers) == 1  # Diversity only; no unmeasured point at the origin.
    assert not any("성향" in text and "자유주의" in text for _, text in texts)

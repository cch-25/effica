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

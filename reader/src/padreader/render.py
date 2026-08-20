"""패드 도안 렌더링.

``spec.py`` 의 상수만 읽어 도안을 그린다. 규격을 바꾸려면 ``spec.py`` 만
고치면 되고, 생성기와 판독기가 같은 상수를 보므로 어긋날 수 없다.

라이브러리에 두는 이유: 합성 검증 이미지 생성기와 회귀 테스트가 도안을
필요로 하는데, ``tools/`` 를 import 하게 만들면 경로 조작이 끼어든다.
``tools/generate_pad.py`` 는 이 모듈을 부르는 얇은 CLI 다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .glyphs import render_text
from .spec import PadSpec, Rect

DEFAULT_QUIET_RATIO = 40 / 1120
"""패드 외곽 바깥에 두는 여백(quiet zone) 비율. 샘플 도안과 같다.

검출기가 테두리 바깥 경계를 잡으려면 패드 밖에 바탕톤 여백이 필요하다.
"""


def tone_levels(tone: str) -> tuple[int, int]:
    """(바탕 밝기, 인쇄 밝기).

    흑색 분진 포인트에는 백색 바탕/흑색 인쇄, 백색 분진 포인트에는 흑색
    바탕/백색 인쇄 패드를 배정한다.
    """
    if tone == "white":
        return 255, 0
    if tone == "black":
        return 0, 255
    raise ValueError(f"패드 톤은 'white' 또는 'black' 이어야 한다: {tone!r}")


class _Canvas:
    """정규화 좌표로 그리는 캔버스."""

    def __init__(self, pad_px: int, quiet_px: int, background: int):
        self.pad_px = pad_px
        self.quiet_px = quiet_px
        size = pad_px + 2 * quiet_px
        self.img = np.full((size, size), background, np.uint8)

    def px(self, value: float) -> int:
        return int(round(self.quiet_px + value * self.pad_px))

    def rect(self, r: Rect, level: int) -> None:
        cv2.rectangle(
            self.img,
            (self.px(r.x0), self.px(r.y0)),
            (self.px(r.x1) - 1, self.px(r.y1) - 1),
            level,
            cv2.FILLED,
        )

    def paste(self, mask: np.ndarray, r: Rect, level: int) -> None:
        """``mask`` 의 잉크 부분만 ``r`` 안에 가운데 정렬해 찍는다.

        종횡비를 유지하며 ``r`` 에 들어가도록 축소한다.
        """
        x0, y0, x1, y1 = self.px(r.x0), self.px(r.y0), self.px(r.x1), self.px(r.y1)
        box_w, box_h = x1 - x0, y1 - y0
        if box_w < 1 or box_h < 1 or mask.size == 0:
            return

        scale = min(box_w / mask.shape[1], box_h / mask.shape[0])
        w = max(1, int(round(mask.shape[1] * scale)))
        h = max(1, int(round(mask.shape[0] * scale)))
        resized = cv2.resize(mask, (w, h), interpolation=cv2.INTER_AREA)

        ox = x0 + (box_w - w) // 2
        oy = y0 + (box_h - h) // 2
        region = self.img[oy : oy + h, ox : ox + w]
        region[resized > 127] = level


def render_pad(
    spec: PadSpec,
    tone: str,
    point_id: str = "1078",
    pad_px: int = 1120,
    quiet_ratio: float = DEFAULT_QUIET_RATIO,
    font_path: str | None = None,
    channels: int = 3,
) -> np.ndarray:
    """패드 도안을 렌더한다.

    Parameters
    ----------
    spec
        패드 규격. ``spec.LEGACY`` 또는 ``spec.V2``.
    tone
        ``white`` = 백색 바탕/흑색 인쇄, ``black`` = 그 반대.
    point_id
        인쇄할 관측 포인트 번호.
    pad_px
        패드 외곽 한 변의 픽셀 수. 캔버스는 여기에 quiet zone 이 더해진다.
    font_path
        POINT_ID 에 쓸 TTF. ``None`` 이면 OpenCV Hershey 로 떨어진다.
        판독기와 **같은 값**을 써야 템플릿 매칭이 성립한다.
    """
    background, ink = tone_levels(tone)
    quiet_px = int(round(pad_px * quiet_ratio))
    canvas = _Canvas(pad_px, quiet_px, background)

    # 굵은 외곽 테두리: 바깥 사각을 인쇄색으로 채우고 안쪽을 바탕색으로 도려낸다.
    canvas.rect(Rect(0.0, 0.0, 1.0, 1.0), ink)
    canvas.rect(spec.inner, background)

    # 모서리 블록 3개. 비어 있는 모서리가 회전 기준이므로 그곳만 건너뛴다.
    blocks = spec.corner_blocks
    for name, rect in blocks.items():
        if name == spec.empty_corner:
            continue
        canvas.rect(rect, ink)

    # 2톤 앵커 패치. 톤에 따라 하나는 바탕색, 하나는 인쇄색이 된다 —
    # 두 값의 차가 정규화의 분모이므로 절대 밝기로 그린다.
    for rect in spec.anchor_white:
        canvas.rect(rect, 255)
    for rect in spec.anchor_black:
        canvas.rect(rect, 0)

    # POINT_ID
    if point_id:
        glyph_h = max(8, int(round(spec.point_id_box.height * pad_px)))
        canvas.paste(render_text(point_id, glyph_h, font_path), spec.point_id_box, ink)

    # 선군 4단
    for bar in spec.line_bars:
        canvas.rect(bar.rect(spec.line_group_x0, spec.line_group_x1), ink)

    if channels == 1:
        return canvas.img
    return cv2.cvtColor(canvas.img, cv2.COLOR_GRAY2BGR)

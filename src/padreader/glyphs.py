"""숫자 글리프 렌더링.

도안 생성기(``tools/generate_pad.py``)와 TARGET_ID 판독기(``target_id.py``)가
**같은 함수**로 글리프를 만든다. 둘이 다른 폰트를 쓰면 템플릿 매칭이 성립하지
않으므로, 폰트 선택은 설정 한 곳에서만 하고 양쪽이 그것을 공유한다.

폰트 경로가 설정되어 있고 Pillow 이 있으면 그 TTF 를 쓴다. 없으면 OpenCV 의
Hershey 스트로크 폰트로 떨어진다 — 추가 의존성이 없고 어느 환경에서나 같은
모양이 나오므로, 생성기와 판독기가 어긋날 일이 없다.

주의: ``assets/`` 의 legacy 샘플은 여기서 만들 수 없는 별도의 볼드 산세리프로
인쇄되어 있다. legacy 도안으로 실제 패드를 찍었다면 TARGET_ID 판독률이
떨어질 수 있으므로, 그 경우 ``target_id.font_path`` 에 실제 인쇄에 쓴 폰트를
지정해야 한다.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

# Hershey 폰트로 떨어질 때 쓸 서체. DUPLEX 가 SIMPLEX 보다 획이 굵어
# 인쇄물에 가깝다.
_HERSHEY = cv2.FONT_HERSHEY_DUPLEX


def _render_pillow(text: str, height_px: int, font_path: str) -> np.ndarray | None:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    # 요청 높이에 맞을 때까지 폰트 크기를 맞춘다. 글리프의 실제 잉크 높이는
    # 폰트 크기와 다르므로 한 번 재고 비례로 보정한 뒤 확정한다.
    probe = ImageFont.truetype(font_path, height_px)
    box = probe.getbbox(text)
    ink_height = box[3] - box[1]
    if ink_height <= 0:
        return None
    size = max(1, int(round(height_px * height_px / ink_height)))

    font = ImageFont.truetype(font_path, size)
    box = font.getbbox(text)
    img = Image.new("L", (box[2] - box[0] + 4, box[3] - box[1] + 4), 0)
    ImageDraw.Draw(img).text((-box[0] + 2, -box[1] + 2), text, font=font, fill=255)
    return np.asarray(img)


def _render_hershey(text: str, height_px: int) -> np.ndarray:
    # getTextSize 로 기준 크기를 잰 뒤 목표 높이에 맞춰 스케일을 정한다.
    base_scale = 10.0
    thickness = max(1, int(round(height_px * 0.16)))
    (_, base_h), _ = cv2.getTextSize(text, _HERSHEY, base_scale, thickness)
    scale = base_scale * height_px / max(base_h, 1)
    thickness = max(1, int(round(height_px * 0.16)))
    (w, h), baseline = cv2.getTextSize(text, _HERSHEY, scale, thickness)

    pad = thickness + 4
    canvas = np.zeros((h + baseline + 2 * pad, w + 2 * pad), np.uint8)
    cv2.putText(
        canvas, text, (pad, pad + h), _HERSHEY, scale, 255, thickness, cv2.LINE_AA
    )
    return canvas


def _tight_crop(img: np.ndarray) -> np.ndarray:
    """잉크가 있는 최소 사각형으로 자른다."""
    ys, xs = np.nonzero(img > 0)
    if ys.size == 0:
        return img
    return img[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


@lru_cache(maxsize=256)
def render_text(text: str, height_px: int, font_path: str | None = None) -> np.ndarray:
    """텍스트를 잉크=255, 배경=0 인 8비트 마스크로 렌더한다.

    반환 배열은 잉크 경계에 딱 맞게 잘려 있고 높이가 정확히 ``height_px`` 는
    아닐 수 있다(글리프마다 실제 잉크 높이가 다르다). 크기를 맞춰야 하는
    쪽에서 리사이즈한다.

    ``lru_cache`` 를 쓰지만 순수 함수라 모듈 무상태성을 깨지 않는다 — 같은
    인자에 항상 같은 배열이 나온다. 호출자가 반환 배열을 수정하면 안 된다.
    """
    if height_px < 1:
        raise ValueError(f"height_px 는 1 이상이어야 한다: {height_px}")

    img: np.ndarray | None = None
    if font_path and Path(font_path).exists():
        img = _render_pillow(text, height_px, font_path)
    if img is None:
        img = _render_hershey(text, height_px)

    cropped = _tight_crop(img)
    return np.ascontiguousarray(cropped)


def digit_templates(height_px: int, font_path: str | None = None) -> dict[str, np.ndarray]:
    """0-9 템플릿. TARGET_ID 판독의 상관 대상이다.

    학습 요소가 아니다 — 우리가 인쇄한 글리프를 그대로 다시 그린 것이며,
    매칭 결과는 상관계수로 설명된다.
    """
    return {str(d): render_text(str(d), height_px, font_path) for d in range(10)}

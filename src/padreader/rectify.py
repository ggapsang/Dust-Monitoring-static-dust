"""정면 시점 보정.

검출된 네 꼭짓점을 고정 규격 정사각형에 대응시켜, 촬영 각도·거리와 무관하게
항상 같은 크기의 정면 이미지를 만든다. 출력 좌표계는 **패드 외곽이 곧
[0, pad_size_px]** 이므로 ``spec`` 의 정규화 좌표에 크기를 곱하면 그대로 ROI 가
된다.

축소 시 앨리어싱에 주의한다. ``warpPerspective`` 는 ``INTER_AREA`` 를 받지
않아, 크게 찍힌 패드를 곧바로 축소하면 화소가 솎여 여백에 없는 얼룩이
생긴다. 분진 신호가 바로 그 미세한 밝기 차이라 그냥 넘길 수 없으므로,
축소율이 크면 먼저 ``INTER_AREA`` 로 정수배 다운샘플한 뒤 warp 한다.
"""

from __future__ import annotations

import cv2
import numpy as np

PRESCALE_THRESHOLD = 1.5
"""이 배율을 넘게 축소해야 하면 미리 다운샘플한다."""


def _prescale(
    image: np.ndarray, corners: np.ndarray, pad_size_px: int
) -> tuple[np.ndarray, np.ndarray]:
    """축소율이 크면 INTER_AREA 로 정수배 줄이고 꼭짓점도 같이 옮긴다."""
    side = float(np.linalg.norm(np.roll(corners, -1, axis=0) - corners, axis=1).mean())
    scale = side / pad_size_px
    if scale <= PRESCALE_THRESHOLD:
        return image, corners

    factor = int(scale)
    if factor < 2:
        return image, corners

    h, w = image.shape[:2]
    reduced = cv2.resize(
        image, (max(1, w // factor), max(1, h // factor)), interpolation=cv2.INTER_AREA
    )
    return reduced, corners / factor


def rectify(
    image: np.ndarray, corners: np.ndarray, pad_size_px: int
) -> tuple[np.ndarray, np.ndarray]:
    """정면 보정 이미지와 사영변환 행렬을 반환한다.

    Parameters
    ----------
    corners
        시계방향 TL, TR, BR, BL. **회전 판정이 끝난** 순서여야 한다.

    Returns
    -------
    (보정 이미지, 3x3 호모그래피). 호모그래피는 ``image`` 좌표 → 보정 좌표다.
    """
    src_image, src_corners = _prescale(image, corners, pad_size_px)

    size = float(pad_size_px)
    dst = np.array([[0, 0], [size, 0], [size, size], [0, size]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(src_corners.astype(np.float32), dst)

    warped = cv2.warpPerspective(
        src_image,
        matrix,
        (pad_size_px, pad_size_px),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return warped, matrix


def crop(image: np.ndarray, rect, pad_size_px: int) -> np.ndarray:
    """정규화 좌표 사각형으로 보정 이미지를 자른다."""
    x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
    h, w = image.shape[:2]
    x0, x1 = max(0, x0), min(w, x1)
    y0, y1 = max(0, y0), min(h, y1)
    return image[y0:y1, x0:x1]

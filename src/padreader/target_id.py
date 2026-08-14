"""TARGET_ID 판독.

정면 보정이 끝난 이미지의 고정 위치에서 숫자를 읽는다. 학습 요소는 쓰지
않는다 — 우리가 인쇄한 것과 같은 글리프를 다시 그려 상관을 재는 것이라
판독 근거가 상관계수 하나로 설명된다.

판독 실패는 판독 불가로 올리지 않는다. 패드 자체는 읽혔고 분진 스코어는
그대로 유효하기 때문이다. 실패는 상태로 표시해 상위 계층이 판단하게 한다.

전제: 인쇄에 쓴 폰트와 판독에 쓰는 폰트가 같아야 한다. 설정의
``target_id.font_path`` 를 도안 생성 때와 같은 값으로 두면 자동으로 맞는다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import TargetIdConfig
from .glyphs import digit_templates
from .rectify import crop
from .result import TargetIdStatus
from .spec import PadSpec

TEMPLATE_HEIGHT = 48
"""템플릿과 후보를 맞춰 놓을 높이. 상관 계산 전에 양쪽을 이 크기로 만든다."""

MIN_COMPONENT_HEIGHT_RATIO = 0.35
"""박스 높이 대비 이보다 낮은 연결요소는 잡티로 본다."""

MAX_COMPONENT_WIDTH_RATIO = 0.6
"""박스 너비 대비 이보다 넓으면 숫자가 아니라 붙어버린 덩어리다."""


def _binarize(patch: np.ndarray, tone: str) -> np.ndarray:
    """인쇄색을 255 로. 톤에 따라 극성을 뒤집어 이후를 통일한다."""
    flag = cv2.THRESH_BINARY_INV if tone == "white" else cv2.THRESH_BINARY
    _, binary = cv2.threshold(patch, 0, 255, flag | cv2.THRESH_OTSU)
    return binary


def _components(binary: np.ndarray) -> list[tuple[int, int, int, int]]:
    """좌에서 우로 정렬한 숫자 후보 박스."""
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    height, width = binary.shape

    boxes: list[tuple[int, int, int, int]] = []
    for label in range(1, count):
        x, y, w, h, area = stats[label]
        if h < height * MIN_COMPONENT_HEIGHT_RATIO:
            continue
        if w > width * MAX_COMPONENT_WIDTH_RATIO:
            continue
        if area < 8:
            continue
        boxes.append((x, y, w, h))

    boxes.sort(key=lambda b: b[0])
    return boxes


def _fit(mask: np.ndarray) -> np.ndarray:
    """상관 비교를 위해 공통 높이로 맞추고 여백을 없앤다."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        return np.zeros((TEMPLATE_HEIGHT, TEMPLATE_HEIGHT), np.uint8)
    cropped = mask[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    scale = TEMPLATE_HEIGHT / cropped.shape[0]
    width = max(1, int(round(cropped.shape[1] * scale)))
    return cv2.resize(
        cropped, (width, TEMPLATE_HEIGHT), interpolation=cv2.INTER_AREA
    )


def _correlate(candidate: np.ndarray, template: np.ndarray) -> float:
    """두 마스크의 정규화 상관. 너비가 다르면 넓은 쪽에 맞춰 패딩한다."""
    width = max(candidate.shape[1], template.shape[1])
    canvas_a = np.zeros((TEMPLATE_HEIGHT, width), np.float32)
    canvas_b = np.zeros((TEMPLATE_HEIGHT, width), np.float32)
    canvas_a[:, : candidate.shape[1]] = candidate
    canvas_b[:, : template.shape[1]] = template

    a = canvas_a - canvas_a.mean()
    b = canvas_b - canvas_b.mean()
    denominator = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denominator < 1e-9:
        return 0.0
    return float((a * b).sum() / denominator)


def read_target_id(
    rectified_gray: np.ndarray,
    spec: PadSpec,
    tone: str,
    cfg: TargetIdConfig,
    pad_size_px: int,
) -> tuple[str | None, TargetIdStatus, float | None]:
    """(읽은 값, 상태, 신뢰도)."""
    if not cfg.enabled:
        return None, TargetIdStatus.DISABLED, None

    patch = crop(rectified_gray, spec.target_id_box, pad_size_px)
    if patch.size == 0:
        return None, TargetIdStatus.FAILED, None

    binary = _binarize(patch, tone)
    boxes = _components(binary)
    if not boxes:
        return None, TargetIdStatus.FAILED, None
    if cfg.digits is not None and len(boxes) != cfg.digits:
        return None, TargetIdStatus.FAILED, None

    templates = {
        digit: _fit(glyph) for digit, glyph in digit_templates(TEMPLATE_HEIGHT).items()
    }

    digits: list[str] = []
    scores: list[float] = []
    for x, y, w, h in boxes:
        candidate = _fit(binary[y : y + h, x : x + w])
        best_digit, best_score = max(
            ((d, _correlate(candidate, t)) for d, t in templates.items()),
            key=lambda pair: pair[1],
        )
        digits.append(best_digit)
        scores.append(best_score)

    # 신뢰도는 가장 약한 자리를 따른다. 한 자리만 틀려도 ID 전체가 틀리므로
    # 평균으로 뭉개면 안 된다.
    confidence = float(min(scores))
    if confidence < cfg.min_confidence:
        return "".join(digits), TargetIdStatus.FAILED, confidence
    return "".join(digits), TargetIdStatus.OK, confidence

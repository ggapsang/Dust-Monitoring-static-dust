"""TARGET_ID 판독.

정면 보정이 끝난 이미지의 고정 위치에서 숫자를 읽는다. 학습 요소는 쓰지
않는다 — 우리가 인쇄한 것과 같은 글리프를 다시 그려 상관을 재는 것이라
판독 근거가 상관계수 하나로 설명된다.

판독 실패는 판독 불가로 올리지 않는다. 패드 자체는 읽혔고 분진 스코어는
그대로 유효하기 때문이다. 실패는 상태로 표시해 상위 계층이 판단하게 한다.

전제: 인쇄에 쓴 폰트와 판독에 쓰는 폰트가 같아야 한다. ``target_id.font_dir``
폴더에 실제 인쇄에 쓴 폰트를 넣어 두면 그것으로 템플릿을 그린다. 폴더가
비어 있으면 내장 스트로크 폰트로 도는데, 인쇄체와 모양이 다르면 자리를
잘못 읽을 수 있다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import TargetIdConfig
from .glyphs import digit_templates, find_fonts
from .rectify import crop
from .result import TargetIdStatus
from .spec import PadSpec

TEMPLATE_HEIGHT = 48
"""템플릿과 후보를 맞춰 놓을 높이. 상관 계산 전에 양쪽을 이 크기로 만든다."""

MIN_COMPONENT_HEIGHT_RATIO = 0.35
"""박스 높이 대비 이보다 낮은 연결요소는 잡티로 본다."""

MAX_COMPONENT_WIDTH_RATIO = 0.6
"""박스 너비 대비 이보다 넓으면 숫자가 아니라 붙어버린 덩어리다."""

MIN_COMPONENT_ASPECT = 0.15
"""높이 대비 이보다 홀쭉하면 숫자가 아니다.

번호 영역 가장자리에 이웃 인쇄물이 걸리면 세로로 긴 조각이 들어와 숫자 하나로
세어진다. 실촬영에서 폭 3px, 높이 54px(종횡비 0.06) 짜리 조각이 앞에 붙어
1086 이 21986 으로 읽혔다. 실제 숫자는 가장 홀쭉한 1 도 0.44 였으므로 이
선으로 갈린다.

가장자리에 닿았는지로 거르지는 않는다. 정합이 조금만 커도 멀쩡한 숫자가
가장자리에 닿는데, 실촬영에서 legacy 패드의 네 자리 중 셋이 그랬다.
"""


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
        if w < h * MIN_COMPONENT_ASPECT:
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

    candidates = [_fit(binary[y : y + h, x : x + w]) for x, y, w, h in boxes]

    # 폰트를 하나로 못 박지 않는다. 현장에 서로 다른 폰트로 인쇄된 패드가
    # 섞여 있을 수 있어서다 — 도안 생성기가 돌아간 장비에 어떤 폰트가 깔려
    # 있었느냐에 따라 같은 도안도 다른 글꼴로 찍힌다. 하나로 정하면 그 종류만
    # 잘 읽히고 나머지는 오히려 못 읽게 된다.
    #
    # 폰트마다 전체를 읽어 보고 **자리별 상관의 평균이 가장 높은** 폰트를
    # 고른다. 자리마다 다른 폰트를 섞지 않는 이유는, 한 패드는 한 폰트로
    # 인쇄되었을 것이고 섞으면 아무 글자에나 억지로 맞춘 답이 나오기 때문이다.
    #
    # 고를 때 최소값을 쓰지 않는다. 분진에 덮인 한 자리가 폰트 선택을 좌우해
    # 버리기 때문이다. 실촬영에서 분진이 많이 쌓인 사진의 정답 폰트가 평균
    # 0.716 인데 최소 0.518 이라, 최소 0.584 인 엉뚱한 폰트에 밀려 한 자리를
    # 틀리게 읽었다. 네 자리 전부를 근거로 삼는 편이 '이 패드가 어느 폰트로
    # 인쇄되었나' 를 더 잘 가른다.
    best: tuple[float, float, str] | None = None
    for font_path in [*find_fonts(cfg.font_dir), None]:
        templates = {
            digit: _fit(glyph)
            for digit, glyph in digit_templates(TEMPLATE_HEIGHT, font_path).items()
        }
        digits: list[str] = []
        scores: list[float] = []
        for candidate in candidates:
            digit, score = max(
                ((d, _correlate(candidate, t)) for d, t in templates.items()),
                key=lambda pair: pair[1],
            )
            digits.append(digit)
            scores.append(score)

        # 신뢰도로 내보내는 값은 여전히 가장 약한 자리다. 한 자리만 틀려도
        # ID 전체가 틀리므로, 상위 계층이 믿을지 말지 볼 때는 평균으로
        # 뭉개면 안 된다. 폰트를 고르는 기준과 신뢰도를 내는 기준이 다르다.
        fit = float(np.mean(scores))
        if best is None or fit > best[0]:
            best = (fit, float(min(scores)), "".join(digits))

    if best is None:
        return None, TargetIdStatus.FAILED, None
    return best[2], TargetIdStatus.OK, best[1]

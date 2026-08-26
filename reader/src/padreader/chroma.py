"""유채색(마젠타) 패드 판독 경로.

기존 흑백 패드는 그대로 둔다 - 이 모듈은 그 옆에 나란히 놓일 새 경로다.
``dust.py``/``score.py`` 는 건드리지 않는다.

패드 종류는 정합 후 측정 여백의 채도로 자동 판별한다(``classify_pad_type``).
유채색으로 판별되면 2톤 앵커로 R·G·B 채널을 각각 정규화하고(``channel_normalize``),
그 위에서 명도·채도 두 필드를 낸다. 셋 다 자유 파라미터(임계값·가중치·차수)가
없다 - 노출 영역 전체를 부호 그대로 합산하고 제곱근을 씌울 뿐이다. 원리는
``optical_density.py`` 의 광학밀도 지표와 같다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .config import DetectConfig
from .detect import Detection
from .geometry import order_corners, quad_area
from .result import ChromaFieldScore, FailureReason
from .spec import PadSpec, Rect, V2_PROTECTED

PAD_TYPE_SATURATION_THRESHOLD = 0.35
"""유채색/무채색 판별 기준. 정합 후 측정 여백의 (max-min)/max 중앙값.

실측 근거 - 무채색(백/흑) 패드 실촬영 77장(136개 검출)의 여백 채도 중앙값은
최소 0.0098, 중앙값 0.0379, **최댓값 0.1843** 이었다(JPEG 압축·카메라 화이트
밸런스 잔차가 전부 포함된 실촬영 값). 마젠타 인쇄 자체의 채도는 도안 원본에서
직접 재면 1.0(RGB 236,0,140) 이다. 두 쪽 사이에 5배 이상의 틈이 있으므로,
그 중간의 어느 값을 잡아도 오분류 위험이 작다. 무채색 실측 최댓값(0.184)의
약 2배, 잉크 채도(1.0)의 1/3 이하인 0.35 를 잡았다.

**한계**: 무채색 쪽은 실촬영으로 뒷받침되지만, 유채색 쪽은 실제 카메라로
찍은 마젠타 패드 사진이 아직 없어 도안 원본(인쇄값 그대로, 카메라 노출·
렌즈·JPEG 압축 영향 없음)으로만 확인했다. 실촬영이 확보되면 이 값을
재검토해야 한다.
"""


def classify_pad_type(
    rectified_bgr: np.ndarray,
    spec: PadSpec,
    pad_size_px: int,
    threshold: float = PAD_TYPE_SATURATION_THRESHOLD,
) -> tuple[str, float]:
    """정합 후 측정 여백의 채도 중앙값으로 ``mono``/``chroma`` 를 가른다.

    앵커 정규화 전 원값으로 본다 - 판별 자체가 정규화의 성패에 앞서야 하고,
    분진이 앉아도(무채색이므로) 채도가 오르는 방향이 아니라 이 판별은
    분진 유무에 흔들리지 않는다.
    """
    mx0, my0, mx1, my1 = spec.margin.to_pixels(pad_size_px)
    region = rectified_bgr[my0:my1, mx0:mx1].astype(np.float64)
    b, g, r = region[..., 0], region[..., 1], region[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    # HSV 의 S 정의와 같다: max=0(순흑)이면 채도 미정 -> 0으로 둔다.
    saturation = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    median_saturation = float(np.median(saturation))
    pad_type = "chroma" if median_saturation > threshold else "mono"
    return pad_type, median_saturation


def detect_pads_chroma(
    bgr: np.ndarray,
    spec: PadSpec,
    cfg: DetectConfig,
    saturation_threshold: float = PAD_TYPE_SATURATION_THRESHOLD,
) -> list[Detection]:
    """유채색 패드를 색으로 직접 찾는다. 무채색 검출(``detect.py``)과 별개
    경로다 - 그쪽은 건드리지 않는다.

    무채색 검출은 "잉크 링 + 그 안의 밝은 구멍"을 밝기로 가른다. 유채색
    패드가 어둡게 찍히면(마젠타가 잉크만큼 어두워지면) 그 밝기 대비가
    사라져 링을 못 찾는다 - 실측 사례: 명도 13~33 인데 채도는 0.91.
    채도는 밝기와 무관하게 남으므로, 측정면(고르게 채도가 높은 사각
    덩어리)을 직접 찾는다.

    측정면의 네 꼭짓점만 찾으면 패드 외곽은 역산으로 나온다 - 측정 여백이
    패드 전체 좌표계에서 정확히 어느 정규화 사각형인지(``spec.margin``)는
    이미 규격에 있고, 같은 평면이므로 사영변환도 하나다.
    """
    height, width = bgr.shape[:2]
    b, g, r = bgr[..., 0].astype(np.float64), bgr[..., 1].astype(np.float64), bgr[..., 2].astype(np.float64)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    saturation = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    mask = (saturation > saturation_threshold).astype(np.uint8) * 255

    # 렌즈 색수차 등 가는 잡음을 지운다. 커널을 사진 짧은 변 대비 비율로
    # 잡아 해상도에 무관하게 만든다 - detect.py 의 local_block_ratio 와
    # 같은 방식.
    k = max(3, int(round(min(height, width) * 0.01)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total_area = float(height * width)
    out: list[Detection] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        ratio = area / total_area
        if ratio < cfg.min_pad_area_ratio or ratio > cfg.max_pad_area_ratio:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, cfg.approx_epsilon_ratio * perimeter, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        hull_area = cv2.contourArea(cv2.convexHull(approx))
        if hull_area <= 0 or area / hull_area < cfg.min_solidity:
            continue

        margin_corners = order_corners(approx.reshape(4, 2).astype(np.float64))
        pad_corners = _pad_corners_from_margin(margin_corners, spec.margin)
        out.append(
            Detection(
                corners=pad_corners,
                coarse_corners=pad_corners,
                area=quad_area(pad_corners),
                # 잉크 링 변 적합이 아니라 색 덩어리 컨투어에서 나온 것이라
                # 그 진단값이 없다 - 뒤(회전 판정·품질 게이트)에서 어차피
                # 다시 검증한다.
                edge_sample_counts=(0, 0, 0, 0),
                edge_residuals=(0.0, 0.0, 0.0, 0.0),
            )
        )

    out.sort(key=lambda d: -d.area)
    return out


def _pad_corners_from_margin(margin_corners_photo: np.ndarray, margin_rect: Rect) -> np.ndarray:
    """측정 여백의 사진 좌표 네 꼭짓점 -> 패드 외곽 네 꼭짓점.

    측정 여백과 패드 외곽은 같은 평면 위의 두 사각형이라 사영변환이 하나로
    통한다. 여백의 정규화 좌표(``margin_rect``)에서 사진 좌표로 가는 변환을
    구하면, 그 변환을 패드 외곽의 정규화 좌표 (0,0)-(1,1) 에 그대로 적용해
    외곽의 사진 좌표를 얻는다.
    """
    src = np.array(
        [
            [margin_rect.x0, margin_rect.y0],
            [margin_rect.x1, margin_rect.y0],
            [margin_rect.x1, margin_rect.y1],
            [margin_rect.x0, margin_rect.y1],
        ],
        dtype=np.float32,
    )
    dst = margin_corners_photo.astype(np.float32)
    transform = cv2.getPerspectiveTransform(src, dst)
    pad_norm = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32).reshape(-1, 1, 2)
    pad_photo = cv2.perspectiveTransform(pad_norm, transform).reshape(4, 2)
    return pad_photo.astype(np.float64)


@dataclass
class ChannelNormalization:
    reflectance: np.ndarray
    """채널별(B,G,R) 정규화 반사율. 정합 이미지 전체 크기, float64.
    흑색 앵커=0, 백색 앵커=1 이 되도록 선형 사상했다."""

    anchor_values: dict[str, list[float]]
    """{"white": [B,G,R], "black": [B,G,R]} - 두 앵커 패치의 raw 관측값(중앙값)."""


def channel_normalize(
    rectified_bgr: np.ndarray, pad_size_px: int
) -> tuple[ChannelNormalization | None, FailureReason | None]:
    """2톤 앵커로 R·G·B 를 채널마다 ``(값-흑) / (백-흑)`` 정규화.

    앵커 좌표는 ``V2_PROTECTED`` 규격의 것을 그대로 쓴다 - 어떤 흑백 규격이
    설정돼 있든(``cfg.spec``), 유채색 패드의 물리적 앵커 위치는 그 도안
    (``make_pad_chroma.py``) 이 2톤 앵커 도안과 동일한 좌표로 찍은 고정값이라
    설정과 무관하다.
    """
    height, width = rectified_bgr.shape[:2]

    def sample(rects) -> np.ndarray:
        pixels = []
        for rect in rects:
            x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
            x1, y1 = min(x1, width), min(y1, height)
            patch = rectified_bgr[y0:y1, x0:x1].astype(np.float64)
            pixels.append(patch.reshape(-1, 3))
        return np.concatenate(pixels, axis=0)

    white_px = sample(V2_PROTECTED.anchor_white)
    black_px = sample(V2_PROTECTED.anchor_black)

    # 클리핑 검사. 8bit 하드 한계 그대로(포화 255, 바닥 0) - 임계값이 아니라
    # 카메라 양자화 한계 자체다.
    if ((white_px <= 0) | (white_px >= 255) | (black_px <= 0) | (black_px >= 255)).any():
        return None, FailureReason.ANCHOR_CLIPPED

    white_med = np.median(white_px, axis=0)  # (B,G,R)
    black_med = np.median(black_px, axis=0)
    span = white_med - black_med
    if np.any(span <= 0):
        return None, FailureReason.ANCHOR_SPAN_INVALID

    reflectance = (rectified_bgr.astype(np.float64) - black_med) / span
    anchor_values = {
        "white": [float(v) for v in white_med[::-1]],  # B,G,R -> R,G,B 순으로 보고
        "black": [float(v) for v in black_med[::-1]],
    }
    return ChannelNormalization(reflectance=reflectance, anchor_values=anchor_values), None


def luma_of(reflectance: np.ndarray) -> np.ndarray:
    """Rec.601 명도. ``0.299R + 0.587G + 0.114B``."""
    b, g, r = reflectance[..., 0], reflectance[..., 1], reflectance[..., 2]
    return 0.299 * r + 0.587 * g + 0.114 * b


def saturation_of(reflectance: np.ndarray) -> np.ndarray:
    """``(max-min)/max`` = HSV 의 S. 채널별 정규화 반사율 위에서 잰다.

    반사율이 앵커 폭을 살짝 벗어나는 화소(잡음, 또는 앵커보다 더 밝거나
    어두운 실제 반사율)가 있을 수 있으므로 [0, 2] 로 눌러 극단값이 나눗셈을
    폭주시키지 않게 한다. 위 여유는 넉넉히 두어 정상 범위(0-1)를 자르지
    않는다.
    """
    clipped = np.clip(reflectance, 0.0, 2.0)
    b, g, r = clipped[..., 0], clipped[..., 1], clipped[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)


def field_score(diff: np.ndarray, measurable: np.ndarray) -> ChromaFieldScore:
    """부호 그대로 합산 -> 평균 -> 제곱근. 임계값 없음. 음수 평균은 0."""
    n = int(measurable.sum())
    if n == 0:
        return ChromaFieldScore()
    total = float(diff[measurable].sum())
    mean = total / n
    score = math.sqrt(mean) if mean > 0 else 0.0
    return ChromaFieldScore(sum=total, mean=mean, score=score)


def clipped_ratio(raw_bgr_region: np.ndarray) -> dict[str, float]:
    """노출 영역 전체에서 채널별 포화·바닥 화소 비율. 진단용, 판정에 안 쓴다."""
    b, g, r = raw_bgr_region[..., 0], raw_bgr_region[..., 1], raw_bgr_region[..., 2]
    n = raw_bgr_region.shape[0] * raw_bgr_region.shape[1]
    out = {}
    for name, ch in (("r", r), ("g", g), ("b", b)):
        out[name] = float(((ch <= 0) | (ch >= 255)).sum() / n) if n else 0.0
    return out


def channel_means(reflectance_region: np.ndarray, measurable: np.ndarray) -> dict[str, float]:
    """노출 영역의 채널별 평균(정규화 반사율)."""
    n = int(measurable.sum())
    if n == 0:
        return {"r": None, "g": None, "b": None}
    b, g, r = reflectance_region[..., 0], reflectance_region[..., 1], reflectance_region[..., 2]
    return {
        "r": float(r[measurable].mean()),
        "g": float(g[measurable].mean()),
        "b": float(b[measurable].mean()),
    }

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

import numpy as np

from .result import ChromaFieldScore, FailureReason
from .spec import PadSpec, V2_PROTECTED

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

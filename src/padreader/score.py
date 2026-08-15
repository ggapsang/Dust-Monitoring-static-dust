"""기준 대비 비교와 스코어 산출.

판독 이미지의 분진에서 기준 이미지의 분진을 뺀다. 그 차이가 패드를 부착한
이후 쌓인 분진이다. 인쇄 농도, 패드 재질, 카메라 개체차, 조명 배치는 두
사진에 똑같이 들어 있으므로 빼는 순간 사라진다.

두 축을 각각 낸다. 같은 양이 쌓여도 넓고 고르게 깔린 것과 한 곳에 뭉친
것은 원인도 대응도 다르기 때문이다.

    고름   = 패드 전체 밝기 변화의 평균
    국소   = 덩어리들 중 가장 크고 짙은 것

종합 지표는 ``u + l - u*l`` 이다. 한쪽만 높아도 종합이 그 값 이상이고, 둘 다
높으면 각각보다 높으며, 한 축이 1 이면 종합도 1 이다. 조정 파라미터는 두지
않는다.
"""

from __future__ import annotations

import cv2
import numpy as np

from .config import DustConfig, ScoreConfig
from .dust import DustMap
from .result import Blob, DustScores


def difference(reading: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    """판독에서 기준을 뺀다. 기준보다 깨끗해진 곳은 0 으로 둔다.

    음수는 분진이 줄었다는 뜻인데, 부착 이후 쌓인 양을 재는 것이 목적이므로
    오염량으로 세지 않는다. 노이즈가 음수 쪽으로 흔들려 값을 깎는 것도 막는다.
    """
    return np.clip(reading - baseline, 0.0, 1.0).astype(np.float32)


def find_blobs(
    depth: np.ndarray, measurable_px: int, cfg: DustConfig
) -> tuple[list[Blob], np.ndarray]:
    """붙어 있는 분진 픽셀을 덩어리로 묶는다. (덩어리 목록, 마스크)."""
    mask = depth > cfg.depth_threshold
    count, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )

    blobs: list[Blob] = []
    for label in range(1, count):
        area = int(stats[label, cv2.CC_STAT_AREA])
        if area < cfg.min_blob_px:
            # 노이즈 한두 화소까지 덩어리로 세면 개수가 의미를 잃는다.
            mask[labels == label] = False
            continue
        pixels = depth[labels == label]
        blobs.append(
            Blob(
                area_px=area,
                area_ratio=area / max(measurable_px, 1),
                mean_depth=float(pixels.mean()),
                max_depth=float(pixels.max()),
                center=(
                    float(centroids[label][0] / max(depth.shape[1], 1)),
                    float(centroids[label][1] / max(depth.shape[0], 1)),
                ),
            )
        )

    # 크고 짙은 순. 국소 스코어가 이 순서의 맨 앞을 쓴다.
    blobs.sort(key=lambda b: b.area_ratio * b.mean_depth, reverse=True)
    return blobs, mask


def _normalize(raw: float, reference: float | None) -> float:
    """원값을 0-1 로. 기준값이 없으면 원값을 그대로 자른다.

    기준값은 '이 정도면 1.0 으로 볼 값' 이며 실증에서 정해야 한다. 비어
    있는 동안에도 스코어가 나오긴 해야 하므로 원값을 그대로 쓴다.
    """
    if reference is None or reference <= 0:
        return float(np.clip(raw, 0.0, 1.0))
    return float(np.clip(raw / reference, 0.0, 1.0))


def compute_scores(
    reading: DustMap,
    baseline: DustMap,
    dust_cfg: DustConfig,
    cfg: ScoreConfig,
) -> tuple[DustScores, list[Blob], np.ndarray]:
    """기준 대비 두 축의 스코어를 낸다.

    Returns
    -------
    (스코어, 덩어리 목록, 고름 차이 맵)
    """
    # 두 사진 모두에서 측정 가능한 곳만 본다. 한쪽이라도 제외된 자리는
    # 비교가 성립하지 않는다.
    measurable = reading.measurable & baseline.measurable
    measurable_px = int(measurable.sum())
    if measurable_px == 0:
        return DustScores(), [], np.zeros(reading.uniform_depth.shape, np.float32)

    uniform_diff = np.where(
        measurable, difference(reading.uniform_depth, baseline.uniform_depth), 0.0
    ).astype(np.float32)
    local_diff = np.where(
        measurable, difference(reading.local_depth, baseline.local_depth), 0.0
    ).astype(np.float32)

    uniform_raw = float(uniform_diff.sum() / measurable_px)

    blobs, _ = find_blobs(local_diff, measurable_px, dust_cfg)
    # 가장 크고 짙은 덩어리 하나가 국소 오염의 크기다. 면적 비율과 짙기를
    # 곱해 '넓게 옅은 것' 과 '좁게 짙은 것' 을 같은 저울에 올린다.
    localized_raw = blobs[0].area_ratio * blobs[0].mean_depth if blobs else 0.0

    uniform = _normalize(uniform_raw, cfg.uniform_reference)
    localized = _normalize(localized_raw, cfg.localized_reference)
    combined = uniform + localized - uniform * localized

    scores = DustScores(
        uniform=uniform,
        localized=localized,
        combined=float(combined),
        uniform_raw=uniform_raw,
        localized_raw=float(localized_raw),
    )
    return scores, blobs, uniform_diff

"""판독 파이프라인.

관측 포인트마다 기준 이미지를 두고, 판독 이미지와 견주어 오염도를 낸다.

    기준 이미지   패드 부착 직후 깨끗한 상태에서 찍은 사진
    판독 이미지   이후 순회 때 같은 위치·각도로 찍은 사진

두 장에 똑같은 처리를 적용한 뒤 마지막에 뺀다.

    검출 -> 방향 판정 -> 정면 보정 -> 품질 게이트 -> 조명 정규화
    -> 분진 픽셀 추출        (여기까지 두 장 각각)
    -> 기준 대비 비교 -> 스코어

AMR 의 촬영 위치와 각도가 포인트마다 고정되어 있으므로 두 사진의 촬영
조건이 같다. 인쇄 농도, 패드 재질, 카메라 개체차, 조명 배치가 두 장에
똑같이 들어 있어 빼는 순간 사라진다. 포인트 간 스코어 비교는 하지 않는다.

회전 판정 때문에 정면 보정을 두 번 한다. 첫 번째는 작게 떠서 어느 모서리가
비어 있는지만 보고, 꼭짓점 순서를 바로잡은 뒤 두 번째를 제 크기로 뜬다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from .config import Config, load_config
from .detect import detect_pad
from .dust import DustMap, extract_dust
from .normalize import normalize
from .orient import apply_rotation, determine_orientation
from .quality import check_gates, measure_quality
from .rectify import rectify
from .result import FailureReason, PadReadResult, QualityMetrics
from .score import compute_scores
from .spec import PadSpec, get_spec
from .target_id import read_target_id
from .visualize import draw_distribution

ORIENT_PREVIEW_PX = 512
"""회전 판정용 미리보기 크기. 모서리 블록만 보면 되므로 클 필요가 없다."""


@dataclass
class _Analysis:
    """사진 한 장을 분진 추출까지 처리한 결과."""

    dust: DustMap
    quality: QualityMetrics
    rotation_deg: int
    rotation_margin: float
    rectified: np.ndarray
    rectified_gray: np.ndarray


def load_image(image: Any) -> np.ndarray | None:
    """경로든 배열이든 BGR 배열로 만든다."""
    if isinstance(image, np.ndarray):
        if image.ndim == 2:
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        if image.ndim == 3 and image.shape[2] == 3:
            return image
        if image.ndim == 3 and image.shape[2] == 4:
            return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        return None

    if isinstance(image, (str, Path)):
        return cv2.imread(str(image), cv2.IMREAD_COLOR)

    return None


def _analyze(
    bgr: np.ndarray, tone: str, cfg: Config, spec: PadSpec
) -> tuple[_Analysis | None, tuple[FailureReason, str] | None]:
    """사진 한 장을 분진 추출까지 처리한다. 실패하면 (None, 사유)."""
    size = cfg.pad_size_px
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    detection = detect_pad(gray, tone, cfg.detect, spec.border_thickness)
    if detection is None:
        return None, (FailureReason.PAD_NOT_FOUND, "테두리 사각형을 찾지 못했다")

    preview, _ = rectify(gray, detection.corners, ORIENT_PREVIEW_PX)
    orientation = determine_orientation(preview, spec, tone, ORIENT_PREVIEW_PX)

    if cfg.orient.min_margin is not None and orientation.margin < cfg.orient.min_margin:
        return None, (
            FailureReason.ROTATION_AMBIGUOUS,
            f"회전 판정 마진 {orientation.margin:.3f} < 임계 {cfg.orient.min_margin:.3f}",
        )

    quality = measure_quality(gray, detection, cfg.quality, spec.border_thickness)
    gate = check_gates(quality, cfg.quality)
    if gate is not None:
        return None, gate

    corners = apply_rotation(detection.corners, orientation.rotation_index)
    rectified_bgr, _ = rectify(bgr, corners, size)
    rectified_gray = cv2.cvtColor(rectified_bgr, cv2.COLOR_BGR2GRAY)

    normalization = normalize(rectified_gray, spec, cfg.normalize, size)
    if normalization is None:
        return None, (
            FailureReason.NORMALIZATION_FAILED,
            "테두리 밝기를 기준으로 삼을 수 없다",
        )

    dust = extract_dust(
        reflectance=normalization.reflectance,
        rectified_gray=rectified_gray,
        spec=spec,
        tone=tone,
        cfg=cfg.dust,
        quality_cfg=cfg.quality,
        pad_size_px=size,
    )

    return (
        _Analysis(
            dust=dust,
            quality=quality,
            rotation_deg=orientation.rotation_deg,
            rotation_margin=orientation.margin,
            rectified=rectified_bgr,
            rectified_gray=rectified_gray,
        ),
        None,
    )


def read_pad(
    image: Any,
    baseline: Any,
    pad_tone: str,
    config: Config | None = None,
    overrides: Mapping[str, Any] | None = None,
    visualize: bool = False,
) -> PadReadResult:
    """기준 이미지와 견주어 판독 이미지의 오염도를 낸다.

    Parameters
    ----------
    image
        판독 이미지. 순회 때 찍은 사진.
    baseline
        기준 이미지. 패드 부착 직후 깨끗할 때 같은 위치·각도로 찍은 사진.
    pad_tone
        ``white`` = 백색 바탕/흑색 인쇄(흑색 분진용),
        ``black`` = 흑색 바탕/백색 인쇄(백색 분진용).
    visualize
        기준 정합 이미지, 판독 정합 이미지, 오염도 분포 이미지를 담을지.
    """
    started = time.perf_counter()

    if pad_tone not in ("white", "black"):
        return PadReadResult.failed(
            FailureReason.INVALID_IMAGE,
            f"패드 톤은 'white' 또는 'black' 이어야 한다: {pad_tone!r}",
        )

    cfg = (config or load_config()).merged(overrides)
    spec = get_spec(cfg.spec)

    def finish(result: PadReadResult) -> PadReadResult:
        result.pad_tone = pad_tone
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return result

    reading_bgr = load_image(image)
    if reading_bgr is None or reading_bgr.size == 0:
        return finish(
            PadReadResult.failed(FailureReason.INVALID_IMAGE, "판독 이미지를 읽을 수 없다")
        )

    baseline_bgr = load_image(baseline)
    if baseline_bgr is None or baseline_bgr.size == 0:
        return finish(
            PadReadResult.failed(FailureReason.INVALID_IMAGE, "기준 이미지를 읽을 수 없다")
        )

    # 기준을 먼저 본다. 기준이 없으면 판독을 아무리 잘 읽어도 오염도를 낼
    # 수 없으므로 여기서 끊는 편이 원인을 찾기 쉽다.
    base, base_error = _analyze(baseline_bgr, pad_tone, cfg, spec)
    if base_error is not None:
        reason, detail = base_error
        return finish(
            PadReadResult.failed(
                FailureReason.BASELINE_UNREADABLE,
                f"기준 이미지를 판독하지 못했다 — {reason.value}: {detail}",
            )
        )
    assert base is not None

    reading, error = _analyze(reading_bgr, pad_tone, cfg, spec)
    if error is not None:
        reason, detail = error
        return finish(PadReadResult.failed(reason, detail))
    assert reading is not None

    partial: dict[str, Any] = {
        "quality": reading.quality,
        "rotation_deg": reading.rotation_deg,
        "rotation_margin": reading.rotation_margin,
    }

    # 두 사진의 패드 크기가 크게 다르면 촬영 위치가 달라진 것이다.
    limit = cfg.quality.max_pad_size_diff_ratio
    reading_size = reading.quality.pad_size_px or 0.0
    baseline_size = base.quality.pad_size_px or 0.0
    largest = max(reading_size, baseline_size)
    size_diff = abs(reading_size - baseline_size) / largest if largest > 0 else 0.0
    if limit is not None and size_diff > limit:
        return finish(
            PadReadResult.failed(
                FailureReason.PAD_SIZE_MISMATCH,
                f"패드 크기 차이 {size_diff:.3f} > 임계 {limit:.3f} "
                f"(판독 {reading_size:.0f}px, 기준 {baseline_size:.0f}px)",
                **partial,
            )
        )

    scores, blobs, uniform_diff = compute_scores(
        reading.dust, base.dust, cfg.dust, cfg.score
    )

    measurable = reading.dust.measurable & base.dust.measurable
    if not measurable.any():
        return finish(
            PadReadResult.failed(
                FailureReason.NO_MEASURABLE_AREA,
                f"제외 후 남은 영역이 없다 ({reading.dust.excluded_pixels})",
                excluded_px=reading.dust.excluded_pixels,
                **partial,
            )
        )

    target_value, target_status, target_confidence = read_target_id(
        reading.rectified_gray, spec, pad_tone, cfg.target_id, cfg.pad_size_px
    )

    kept = blobs if cfg.dust.max_blobs is None else blobs[: cfg.dust.max_blobs]
    result = PadReadResult(
        success=True,
        scores=scores,
        blobs=kept,
        blob_count=len(blobs),
        measurable_px=int(measurable.sum()),
        excluded_px=reading.dust.excluded_pixels,
        pad_size_diff_ratio=size_diff,
        target_id=target_value,
        target_id_status=target_status,
        target_id_confidence=target_confidence,
        **partial,
    )

    if visualize:
        result.baseline_rectified = base.rectified
        result.rectified = reading.rectified
        result.distribution = draw_distribution(
            reading.rectified,
            uniform_diff,
            measurable,
            reading.dust.origin,
            scores,
            spec,
            cfg.pad_size_px,
            cfg.visualize.heat_max,
        )

    return finish(result)

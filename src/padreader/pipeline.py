"""판독 파이프라인.

사진 **두 장**을 받아 결과 객체 하나를 돌려주는 순수 함수다.

    기준 사진   패드 부착 직후 깨끗한 상태에서 찍은 것
    판독 사진   이후 순회 때 같은 패드를 찍은 것

두 장에 똑같은 처리를 적용한 뒤, 판독 사진의 칸값에서 기준 사진의 같은
칸값을 뺀다. 그 차이가 오염량이다.

사진 한 장의 절대값을 스코어로 쓰면 깨끗할 때 얼마였는지를 알 수 없어 오염
여부를 판단할 수 없다. 인쇄 농도, 패드 재질, 카메라 개체차가 값에 다 섞여
있기 때문이다. 같은 관측 포인트에서 같은 카메라로 찍은 두 장을 빼면 그
공통분이 사라진다.

한 장에 적용하는 처리는 다음과 같다.

    검출 -> 회전 판정 -> 정면 보정 -> 품질 게이트 -> 조도 정규화
    -> 구획 측정 -> 비분진 배제

회전 판정 때문에 정면 보정을 두 번 한다. 첫 번째는 작게 떠서 어느 모서리가
비어 있는지만 보고, 꼭짓점 순서를 바로잡은 뒤 두 번째를 제 크기로 뜬다.

전역 상태도 캐시도 갖지 않는다. 같은 두 장이면 언제 몇 번을 부르든 같은
값이 나온다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from .cells import CellGrid, measure_cells
from .config import Config, load_config
from .detect import detect_pad
from .lines import measure_lines
from .normalize import normalize
from .orient import apply_rotation, determine_orientation
from .quality import check_gates, measure_quality
from .rectify import rectify
from .result import (
    FailureReason,
    LineContrast,
    NormalizationInfo,
    PadReadResult,
    QualityMetrics,
    TargetIdStatus,
)
from .score import apply_soiling, compute_score, subtract_baseline
from .spec import PadSpec, get_spec
from .target_id import read_target_id
from .visualize import draw_overlay

ORIENT_PREVIEW_PX = 512
"""회전 판정용 미리보기 크기. 모서리 블록만 보면 되므로 클 필요가 없다."""


@dataclass
class _Analysis:
    """사진 한 장을 끝까지 처리한 결과."""

    grid: CellGrid
    quality: QualityMetrics
    normalization: NormalizationInfo
    rotation_deg: int
    rotation_margin: float
    corners: list[list[float]]
    target_id: str | None
    target_id_status: TargetIdStatus
    target_id_confidence: float | None
    line_contrasts: list[LineContrast]
    rectified: np.ndarray


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
    bgr: np.ndarray,
    tone: str,
    cfg: Config,
    spec: PadSpec,
) -> tuple[_Analysis | None, tuple[FailureReason, str] | None]:
    """사진 한 장을 처리한다. 실패하면 (None, 사유)."""
    size = cfg.pad_size_px
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    detection = detect_pad(gray, tone, cfg.detect)
    if detection is None:
        return None, (FailureReason.PAD_NOT_FOUND, "테두리 사각형을 찾지 못했다")

    preview, _ = rectify(gray, detection.corners, ORIENT_PREVIEW_PX)
    orientation = determine_orientation(preview, spec, tone, ORIENT_PREVIEW_PX)

    if cfg.orient.min_margin is not None and orientation.margin < cfg.orient.min_margin:
        return None, (
            FailureReason.ROTATION_AMBIGUOUS,
            f"회전 판정 마진 {orientation.margin:.3f} < 임계 {cfg.orient.min_margin:.3f}"
            f" (모서리 잉크도 {orientation.corner_inkness})",
        )

    corners = apply_rotation(detection.corners, orientation.rotation_index)
    rectified_bgr, _ = rectify(bgr, corners, size)
    rectified_gray = cv2.cvtColor(rectified_bgr, cv2.COLOR_BGR2GRAY)

    quality = measure_quality(gray, detection, cfg.quality, spec.border_thickness)

    normalization = normalize(rectified_gray, spec, tone, cfg.normalize, size)
    if normalization is None:
        return None, (
            FailureReason.QUALITY_ANCHOR_CONTRAST,
            "조도 기준을 세울 수 없다 (앵커 또는 테두리 대비 부족)",
        )

    if normalization.info.anchor_white is not None and normalization.info.anchor_black is not None:
        quality.anchor_contrast = float(
            normalization.info.anchor_white - normalization.info.anchor_black
        )

    gate = check_gates(quality, cfg.quality)
    if gate is not None:
        return None, gate

    grid = measure_cells(
        reflectance=normalization.reflectance,
        rectified_bgr=rectified_bgr,
        rectified_gray=rectified_gray,
        spec=spec,
        scale=normalization.scale,
        grid_cfg=cfg.grid,
        exclude_cfg=cfg.exclude,
        quality_cfg=cfg.quality,
        pad_size_px=size,
    )
    apply_soiling(grid.cells, tone)

    target_value, target_status, target_confidence = read_target_id(
        rectified_gray, spec, tone, cfg.target_id, size
    )
    line_contrasts = (
        measure_lines(normalization.reflectance, spec, size) if cfg.lines.enabled else []
    )

    return (
        _Analysis(
            grid=grid,
            quality=quality,
            normalization=normalization.info,
            rotation_deg=orientation.rotation_deg,
            rotation_margin=orientation.margin,
            corners=corners.tolist(),
            target_id=target_value,
            target_id_status=target_status,
            target_id_confidence=target_confidence,
            line_contrasts=line_contrasts,
            rectified=rectified_bgr,
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
    """기준 사진과 견주어 판독 사진의 오염량을 낸다.

    Parameters
    ----------
    image
        판독 사진. 순회 때 찍은 것. 파일 경로 또는 BGR/그레이 배열.
    baseline
        기준 사진. 패드 부착 직후 깨끗할 때 찍은 것. 같은 관측 포인트에서
        같은 카메라로 찍은 것이어야 한다.
    pad_tone
        ``white`` = 백색 바탕/흑색 인쇄, ``black`` = 흑색 바탕/백색 인쇄.
    config
        설정. 없으면 기본 설정을 읽는다.
    overrides
        설정 일부만 덮어쓸 때. 원본 설정은 바뀌지 않는다.
    visualize
        정면 보정 이미지와 구획 시각화를 결과에 담을지.
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
        result.spec_name = spec.name
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return result

    reading_bgr = load_image(image)
    if reading_bgr is None or reading_bgr.size == 0:
        return finish(
            PadReadResult.failed(FailureReason.INVALID_IMAGE, "판독 사진을 읽을 수 없다")
        )

    baseline_bgr = load_image(baseline)
    if baseline_bgr is None or baseline_bgr.size == 0:
        return finish(
            PadReadResult.failed(FailureReason.INVALID_IMAGE, "기준 사진을 읽을 수 없다")
        )

    # 기준 사진을 먼저 처리한다. 기준이 없으면 판독 사진을 아무리 잘 읽어도
    # 오염량을 낼 수 없으므로 여기서 끊는 편이 낫다.
    base_analysis, base_error = _analyze(baseline_bgr, pad_tone, cfg, spec)
    if base_error is not None:
        reason, detail = base_error
        return finish(
            PadReadResult.failed(
                FailureReason.BASELINE_UNREADABLE,
                f"기준 사진을 판독하지 못했다 — {reason.value}: {detail}",
            )
        )
    assert base_analysis is not None

    analysis, error = _analyze(reading_bgr, pad_tone, cfg, spec)
    partial: dict[str, Any] = {}
    if analysis is not None:
        partial = {
            "quality": analysis.quality,
            "normalization": analysis.normalization,
            "rotation_deg": analysis.rotation_deg,
            "rotation_margin": analysis.rotation_margin,
            "corners": analysis.corners,
        }
    if error is not None:
        reason, detail = error
        return finish(PadReadResult.failed(reason, detail, **partial))
    assert analysis is not None

    # 두 사진이 서로 다른 방식으로 정규화되면 척도가 달라 뺄셈이 아무
    # 의미도 없어진다. 도안 원본(잉크가 정확히 0)을 기준 사진 자리에 넣고
    # 실제 촬영본을 판독 사진으로 넣으면 여기 걸린다 — 기준 사진은 같은
    # 카메라로 찍은 **사진**이어야 한다.
    if analysis.normalization.method != base_analysis.normalization.method:
        return finish(
            PadReadResult.failed(
                FailureReason.NORMALIZATION_MISMATCH,
                f"두 사진의 조도 정규화 방식이 다르다 "
                f"(판독 {analysis.normalization.method}, 기준 {base_analysis.normalization.method}). "
                f"기준 사진은 도안 파일이 아니라 같은 카메라로 찍은 사진이어야 한다.",
                **partial,
            )
        )

    if len(analysis.grid.cells) != len(base_analysis.grid.cells):
        return finish(
            PadReadResult.failed(
                FailureReason.GRID_MISMATCH,
                f"격자가 어긋난다: 판독 {len(analysis.grid.cells)}칸, "
                f"기준 {len(base_analysis.grid.cells)}칸",
                **partial,
            )
        )

    cells = subtract_baseline(analysis.grid.cells, base_analysis.grid.cells)

    excluded = [c for c in cells if c.excluded is not None]
    by_reason: dict[str, int] = {}
    for cell in excluded:
        assert cell.excluded is not None
        by_reason[cell.excluded.value] = by_reason.get(cell.excluded.value, 0) + 1

    scored = compute_score(cells, cfg.score)
    if scored is None:
        return finish(
            PadReadResult.failed(
                FailureReason.NO_VALID_CELLS,
                f"{len(cells)}개 구획이 모두 배제되었다 ({by_reason})",
                cells=cells,
                grid_shape=(analysis.grid.rows, analysis.grid.cols),
                excluded_count=len(excluded),
                excluded_by_reason=by_reason,
                **partial,
            )
        )

    score, dispersion = scored

    result = PadReadResult(
        success=True,
        dust_score=score,
        score_statistic=cfg.score.statistic,
        dispersion=dispersion,
        cells=cells,
        grid_shape=(analysis.grid.rows, analysis.grid.cols),
        excluded_count=len(excluded),
        excluded_by_reason=by_reason,
        line_contrasts=analysis.line_contrasts,
        target_id=analysis.target_id,
        target_id_status=analysis.target_id_status,
        target_id_confidence=analysis.target_id_confidence,
        **partial,
    )

    if visualize:
        result.rectified = analysis.rectified
        result.overlay = draw_overlay(
            analysis.rectified, CellGrid(cells, analysis.grid.rows, analysis.grid.cols, analysis.grid.bounds), spec, cfg.pad_size_px
        )

    return finish(result)

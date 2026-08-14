"""판독 파이프라인.

이미지 1장을 받아 결과 객체 하나를 돌려주는 순수 함수다. 전역 상태도,
기준 이미지도, 캐시도 갖지 않는다 — 같은 입력이면 언제 몇 번을 부르든
같은 값이 나와야 한다.

    검출 -> 회전 판정 -> 정면 보정 -> 품질 게이트 -> 조도 정규화
    -> 구획 측정 -> 비분진 배제 -> 스코어

회전 판정 때문에 정면 보정을 두 번 한다. 첫 번째는 작게 떠서 어느 모서리가
비어 있는지만 보고, 꼭짓점 순서를 바로잡은 뒤 두 번째를 제 크기로 뜬다.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from .cells import measure_cells
from .config import Config, load_config
from .detect import detect_pad
from .lines import measure_lines
from .normalize import normalize
from .orient import apply_rotation, determine_orientation
from .quality import check_gates, measure_quality
from .rectify import rectify
from .result import FailureReason, PadReadResult, TargetIdStatus
from .score import apply_soiling, compute_score
from .spec import get_spec
from .target_id import read_target_id
from .visualize import draw_overlay

ORIENT_PREVIEW_PX = 512
"""회전 판정용 미리보기 크기. 모서리 블록만 보면 되므로 클 필요가 없다."""


def _load_image(image: Any) -> np.ndarray | None:
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
        loaded = cv2.imread(str(image), cv2.IMREAD_COLOR)
        return loaded

    return None


def read_pad(
    image: Any,
    pad_tone: str,
    config: Config | None = None,
    overrides: Mapping[str, Any] | None = None,
    visualize: bool = False,
) -> PadReadResult:
    """참조 패드 이미지 1장을 판독한다.

    Parameters
    ----------
    image
        이미지 파일 경로 또는 BGR/그레이 배열.
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
            FailureReason.INVALID_IMAGE, f"패드 톤은 'white' 또는 'black' 이어야 한다: {pad_tone!r}"
        )

    cfg = (config or load_config()).merged(overrides)
    spec = get_spec(cfg.spec)
    size = cfg.pad_size_px

    def finish(result: PadReadResult) -> PadReadResult:
        result.pad_tone = pad_tone
        result.spec_name = spec.name
        result.elapsed_ms = (time.perf_counter() - started) * 1000.0
        return result

    bgr = _load_image(image)
    if bgr is None or bgr.size == 0:
        return finish(
            PadReadResult.failed(FailureReason.INVALID_IMAGE, "이미지를 읽을 수 없다")
        )

    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)

    detection = detect_pad(gray, pad_tone, cfg.detect)
    if detection is None:
        return finish(
            PadReadResult.failed(FailureReason.PAD_NOT_FOUND, "테두리 사각형을 찾지 못했다")
        )

    preview, _ = rectify(gray, detection.corners, ORIENT_PREVIEW_PX)
    orientation = determine_orientation(preview, spec, pad_tone, ORIENT_PREVIEW_PX)

    quality = measure_quality(gray, detection, cfg.quality, spec.border_thickness)
    partial: dict[str, Any] = {
        "quality": quality,
        "rotation_deg": orientation.rotation_deg,
        "rotation_margin": orientation.margin,
        "corners": detection.corners.tolist(),
    }

    if cfg.orient.min_margin is not None and orientation.margin < cfg.orient.min_margin:
        return finish(
            PadReadResult.failed(
                FailureReason.ROTATION_AMBIGUOUS,
                f"회전 판정 마진 {orientation.margin:.3f} < 임계 {cfg.orient.min_margin:.3f}"
                f" (모서리 잉크도 {orientation.corner_inkness})",
                **partial,
            )
        )

    corners = apply_rotation(detection.corners, orientation.rotation_index)
    partial["corners"] = corners.tolist()

    rectified_bgr, _ = rectify(bgr, corners, size)
    rectified_gray = cv2.cvtColor(rectified_bgr, cv2.COLOR_BGR2GRAY)

    normalization = normalize(rectified_gray, spec, pad_tone, cfg.normalize, size)
    if normalization is None:
        return finish(
            PadReadResult.failed(
                FailureReason.QUALITY_ANCHOR_CONTRAST,
                "조도 기준을 세울 수 없다 (앵커 또는 테두리 대비 부족)",
                **partial,
            )
        )

    if normalization.info.anchor_white is not None and normalization.info.anchor_black is not None:
        quality.anchor_contrast = float(
            normalization.info.anchor_white - normalization.info.anchor_black
        )

    gate = check_gates(quality, cfg.quality)
    if gate is not None:
        reason, detail = gate
        partial["normalization"] = normalization.info
        return finish(PadReadResult.failed(reason, detail, **partial))

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
    apply_soiling(grid.cells, pad_tone)

    excluded = [c for c in grid.cells if c.excluded is not None]
    by_reason: dict[str, int] = {}
    for cell in excluded:
        assert cell.excluded is not None
        by_reason[cell.excluded.value] = by_reason.get(cell.excluded.value, 0) + 1

    scored = compute_score(grid.cells, cfg.score)
    if scored is None:
        return finish(
            PadReadResult.failed(
                FailureReason.NO_VALID_CELLS,
                f"{len(grid.cells)}개 구획이 모두 배제되었다 ({by_reason})",
                normalization=normalization.info,
                cells=grid.cells,
                grid_shape=(grid.rows, grid.cols),
                excluded_count=len(excluded),
                excluded_by_reason=by_reason,
                **partial,
            )
        )

    score, dispersion = scored

    target_value, target_status, target_confidence = read_target_id(
        rectified_gray, spec, pad_tone, cfg.target_id, size
    )

    line_contrasts = (
        measure_lines(normalization.reflectance, spec, size) if cfg.lines.enabled else []
    )

    result = PadReadResult(
        success=True,
        dust_score=score,
        score_statistic=cfg.score.statistic,
        dispersion=dispersion,
        cells=grid.cells,
        grid_shape=(grid.rows, grid.cols),
        excluded_count=len(excluded),
        excluded_by_reason=by_reason,
        normalization=normalization.info,
        line_contrasts=line_contrasts,
        target_id=target_value,
        target_id_status=target_status,
        target_id_confidence=target_confidence,
        **partial,
    )

    if visualize:
        result.rectified = rectified_bgr
        result.overlay = draw_overlay(rectified_bgr, grid, spec, size)

    return finish(result)

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
from itertools import permutations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np

from .chroma import (
    channel_normalize,
    channel_means,
    classify_pad_type,
    clipped_ratio,
    detect_pads_chroma,
    field_score,
    luma_of,
    saturation_of,
)
from .config import Config, PointIdConfig, load_config
from .detect import Detection, border_fit_error, detect_pads
from .dust import DustMap, extract_dust
from .normalize import normalize
from .optical_density import compute_optical_density
from .orient import apply_rotation, determine_orientation
from .quality import check_gates, measure_quality
from .rectify import rectify
from .result import (
    ChromaDiagnostics,
    ChromaNormalizationInfo,
    FailureReason,
    PadReadBatch,
    PadReadResult,
    QualityMetrics,
    Verification,
)
from .score import compute_scores
from .spec import PadSpec, get_spec
from .point_id import extract_glyphs, match_score, read_point_id
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
    reflectance: np.ndarray
    """조명 정규화된 상대 밝기(테두리=1). ``dust.local_depth`` 는 이미 국소
    배경을 뺀 값이라 광학밀도 지표(시험)에는 못 쓴다 - 이건 그 전 단계다."""
    normalization_scale: float | None
    """이 사진의 테두리 밝기(raw 0-255 척도). ``reflectance = gray/이 값``.
    광학밀도 지표의 8비트 양자화 하한을 reflectance 척도로 되돌리는 데 쓴다."""
    pad_type: str
    """판별된 패드 종류. ``mono`` 또는 ``chroma``."""
    chroma_reflectance: np.ndarray | None
    """2톤 앵커로 채널별 정규화한 반사율(정합 이미지 전체 크기). ``mono`` 이거나
    앵커 정규화에 실패했으면 ``None``."""
    chroma_failure: FailureReason | None
    """유채색인데 앵커 정규화에 실패했으면 그 사유. 그 외에는 ``None``."""
    chroma_anchor_values: dict[str, Any] | None
    """앵커 두 패치의 raw 관측값(채널별). **실패해도 채운다** - 왜 실패했는지는
    사유 이름이 아니라 이 값이 말해 준다."""
    anchor_contrast: float | None
    """``흰 앵커 - 검은 앵커`` 의 채널 평균(raw). 음수면 앵커 자리를 흑백 반대로
    짚고 있다는 뜻이다. 무채색이면 ``None``."""
    border_fit_error: float | None
    """잉크 띠 두께가 규격에서 벗어난 정도(패드 한 변 대비). 검출한 사각형이
    정말 패드 경계인지의 잔차다."""
    point_id: str | None
    point_id_status: Any
    point_id_confidence: float | None
    point_id_raw: str | None = None
    """열린 판독으로 읽은 번호. 후보에 배정해 ``point_id`` 가 바뀌어도 남는다.

    나중에 오독이 몇 건이었는지 세려면 배정 결과와 실제로 읽은 값이 따로
    있어야 한다.
    """

    glyphs: list[Any] = field(default_factory=list)
    """번호 영역에서 잘라 낸 글자 마스크. 후보 배정에 쓴다."""


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


def _analyze_all(
    bgr: np.ndarray, tone: str, cfg: Config, spec: PadSpec, mode: str = "auto"
) -> list[_Analysis]:
    """사진에서 찾은 패드를 전부 분진 추출까지 처리한다.

    패드 하나가 품질 게이트에 걸려도 나머지는 계속 본다. 한 화면에 여러 개가
    찍혔을 때 하나 때문에 전부 버릴 이유가 없다.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    # 유채색 패드는 규격이 따로다. 현장에 붙은 유채색 도안의 좌표가 무채색
    # 규격(cfg.spec)과 달라서, 그쪽 좌표로 재면 앵커도 측정면도 어긋난다.
    spec = get_spec(cfg.chroma.spec) if mode == "chroma" else spec
    # mode="chroma" 는 무채색 검출(잉크 링 찾기)을 아예 안 쓴다 - 유채색
    # 측정면이 어둡게 찍히면 잉크와 밝기로 안 갈려 링 자체가 안 잡히기
    # 때문이다(실측: 명도 13인데 채도는 0.91). 색으로 직접 찾는
    # detect_pads_chroma 를 쓴다. 무채색 경로(detect_pads)는 그대로 둔다.
    detections = (
        detect_pads_chroma(bgr, spec, cfg.detect, cfg.chroma.detect_saturation_threshold)
        if mode == "chroma"
        else detect_pads(gray, tone, cfg.detect, spec.border_thickness)
    )
    out: list[_Analysis] = []
    for detection in detections:
        found, _ = _analyze(bgr, gray, detection, tone, cfg, spec, mode)
        if found is not None:
            out.append(found)
    return out


def _analyze(
    bgr: np.ndarray,
    gray: np.ndarray,
    detection: Detection,
    tone: str,
    cfg: Config,
    spec: PadSpec,
    mode: str = "auto",
) -> tuple[_Analysis | None, tuple[FailureReason, str] | None]:
    """검출된 패드 하나를 분진 추출까지 처리한다. 실패하면 (None, 사유)."""
    size = cfg.pad_size_px

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

    # 유채색 패드 판별과 앵커 정규화. mode="legacy" 면 시도조차 하지 않고
    # 무채색 경로만 돈다 - 기존 흑백 판독 결과가 이 기능 추가로 바뀌면 안 된다.
    pad_type = "mono"
    chroma_reflectance: np.ndarray | None = None
    chroma_failure: FailureReason | None = None
    chroma_anchor_values: dict[str, Any] | None = None
    anchor_contrast: float | None = None

    def calibrate() -> None:
        nonlocal chroma_reflectance, chroma_failure, chroma_anchor_values, anchor_contrast
        norm = channel_normalize(rectified_bgr, size, spec)
        # 실패해도 앵커 실측값은 남긴다. 사유 이름만으로는 좌표가 어긋난
        # 것인지 사진이 나쁜 것인지 밖에서 가릴 수 없다.
        chroma_reflectance = norm.reflectance
        chroma_failure = norm.failure
        chroma_anchor_values = norm.anchor_values
        anchor_contrast = norm.anchor_contrast

    if mode == "chroma":
        # 색으로 직접 찾은 것이니 이미 유채색이라는 게 확정이다 - 다시
        # 판별할 필요 없이 바로 채널 정규화로 간다.
        pad_type = "chroma"
        calibrate()
    elif mode != "legacy":
        pad_type, _saturation = classify_pad_type(
            rectified_bgr, spec, size, cfg.chroma.saturation_threshold
        )
        if pad_type == "chroma":
            calibrate()

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

    # 번호는 여기서 읽는다. 한 화면에 여러 패드가 찍히면 이 번호가 기준
    # 사진의 어느 패드와 짝인지 가리는 열쇠가 된다.
    target_value, target_status, target_confidence = read_point_id(
        rectified_gray, spec, tone, cfg.point_id, size
    )

    return (
        _Analysis(
            dust=dust,
            quality=quality,
            rotation_deg=orientation.rotation_deg,
            rotation_margin=orientation.margin,
            rectified=rectified_bgr,
            rectified_gray=rectified_gray,
            reflectance=normalization.reflectance,
            normalization_scale=normalization.scale,
            pad_type=pad_type,
            chroma_reflectance=chroma_reflectance,
            chroma_failure=chroma_failure,
            chroma_anchor_values=chroma_anchor_values,
            anchor_contrast=anchor_contrast,
            # 무채색 검출은 이미 이 잔차로 걸러 통과한 것만 여기 온다. 유채색
            # 검출은 아직 걸러 내지 않으므로, 이 값이 곧 "색으로 찾은 사각형이
            # 정말 패드였는지" 를 사후에 볼 수 있는 유일한 근거다.
            border_fit_error=border_fit_error(
                gray, corners, tone, spec.border_thickness
            ),
            point_id=target_value,
            point_id_status=target_status,
            point_id_confidence=target_confidence,
            point_id_raw=target_value,
            glyphs=extract_glyphs(rectified_gray, spec, tone, cfg.point_id, size),
        ),
        None,
    )


def assign_ids(
    readings: list[_Analysis], candidates: list[str], cfg: PointIdConfig
) -> None:
    """찍힌 패드들을 후보 번호에 배정한다. 닫힌 판독이다.

    열린 판독은 자리마다 0~9 중 가장 닮은 것을 고른다. 네 자리면 경우의 수가
    1만 개라, 한 자리만 흔들려도 있지도 않은 번호가 나온다 - 실촬영에서 1081
    이 1011 로, 1086 이 1088 로 읽혔다. 자리당 정확도가 99% 여도 네 자리를
    다 맞출 확률은 96% 이고, 개소가 1000개면 40건이 틀린다.

    그런데 그 사진에 무엇이 찍혔는지는 부르는 쪽이 이미 안다. 후보 안에서
    고르면 없는 번호가 나올 수 없고, 패드와 후보를 **통째로** 짝지으면 서로
    밀어내며 제자리를 찾는다. 실촬영 10건에서 열린 판독 7건, 닫힌 판독
    10건이 맞았다.

    자리마다 따로 고르지 않고 배정 전체의 점수 합으로 정한다. 한 패드가
    욕심내 가져간 번호 때문에 다른 패드가 밀리는 것을 막는다.

    후보 중 가장 나은 것이라도 ``assign_min_score`` 에 못 미치면 배정하지
    않는다. 엉뚱한 자리에 붙인 패드나 오검출된 사각형이 조용히 어느 개소로
    배정되는 것이 실패보다 나쁘다.
    """
    if not readings or not candidates:
        return

    floor = cfg.assign_min_score
    table = [[match_score(r.glyphs, c, cfg) for c in candidates] for r in readings]

    best_total = None
    best_plan: tuple[int | None, ...] = ()
    width = min(len(readings), len(candidates))
    for picked in permutations(range(len(candidates)), width):
        plan: list[int | None] = list(picked) + [None] * (len(readings) - width)
        total = sum(
            table[i][j] for i, j in enumerate(plan) if j is not None
        )
        if best_total is None or total > best_total:
            best_total, best_plan = total, tuple(plan)

    # 자리 번호로 찾는다. dataclass 를 값으로 비교하면 안에 든 이미지 배열까지
    # 견주게 되어 터진다.
    for index, choice in enumerate(best_plan):
        if choice is None:
            continue
        score = table[index][choice]
        if floor is not None and score < floor:
            continue
        readings[index].point_id = candidates[choice]
        readings[index].point_id_confidence = score


def read_pads(
    image: Any,
    baseline: Any,
    pad_tone: str,
    config: Config | None = None,
    overrides: Mapping[str, Any] | None = None,
    visualize: bool = False,
    expected_ids: list[str] | None = None,
    mode: str = "auto",
) -> PadReadBatch:
    """기준 사진과 견주어 판독 사진에 찍힌 **모든** 패드의 오염도를 낸다.

    한 화면에 패드가 여러 개 찍히는 일이 현장에서 실제로 일어난다. 가장 크게
    찍힌 하나만 돌려주면 나머지는 조용히 사라지고, 어느 것이 돌아왔는지도 알
    수 없다.

    **기준은 사진이 아니라 패드 단위다.** 한 화면의 패드들은 부착 시점이 서로
    달라 각자의 기준 사진을 갖는다. 그래서 기준을 여러 장 받고, 거기서 찾은
    패드를 번호로 색인해 판독 패드와 짝짓는다. 짝이 없는 판독 패드는 버리지
    않고 실패로 남긴다 — 조용히 사라지면 오검출인지 기준 누락인지 알 수 없다.

    Parameters
    ----------
    image
        판독 이미지. 순회 때 찍은 사진.
    baseline
        기준 이미지. 한 장이거나 여러 장의 목록. 패드 부착 직후 깨끗할 때 같은
        위치·각도로 찍은 사진이다. 그 자리에서 보이는 패드보다 많이 보내도
        되고, 짝이 없는 기준은 그냥 쓰이지 않는다.
    pad_tone
        ``white`` = 백색 바탕/흑색 인쇄(흑색 분진용),
        ``black`` = 흑색 바탕/백색 인쇄(백색 분진용).
    visualize
        패드마다 기준 정합, 판독 정합, 오염도 분포 이미지를 담을지.
    mode
        ``"auto"``(기본) 면 패드 종류(무채색/유채색)를 판별해 유채색이면
        새 경로도 함께 낸다. ``"legacy"`` 면 판별 자체를 하지 않고 항상
        기존 무채색 경로만 돈다 - 유채색 패드가 와도 색을 못 본 것처럼
        처리한다.
    """
    started = time.perf_counter()

    def finish(batch: PadReadBatch) -> PadReadBatch:
        batch.pad_tone = pad_tone
        batch.elapsed_ms = (time.perf_counter() - started) * 1000.0
        for pad in batch.pads:
            pad.pad_tone = pad_tone
            pad.elapsed_ms = batch.elapsed_ms
        return batch

    if pad_tone not in ("white", "black"):
        return finish(PadReadBatch.failed(
            FailureReason.INVALID_IMAGE,
            f"패드 톤은 'white' 또는 'black' 이어야 한다: {pad_tone!r}",
        ))

    cfg = (config or load_config()).merged(overrides)
    spec = get_spec(cfg.spec)

    reading_bgr = load_image(image)
    if reading_bgr is None or reading_bgr.size == 0:
        return finish(PadReadBatch.failed(
            FailureReason.INVALID_IMAGE, "판독 이미지를 읽을 수 없다"))

    sources = baseline if isinstance(baseline, (list, tuple)) else [baseline]
    if not sources:
        return finish(PadReadBatch.failed(
            FailureReason.INVALID_IMAGE, "기준 이미지가 없다"))

    bases: list[_Analysis] = []
    for index, source in enumerate(sources):
        baseline_bgr = load_image(source)
        if baseline_bgr is None or baseline_bgr.size == 0:
            return finish(PadReadBatch.failed(
                FailureReason.INVALID_IMAGE,
                f"기준 이미지를 읽을 수 없다 ({index + 1}번째)"))
        bases.extend(_analyze_all(baseline_bgr, pad_tone, cfg, spec, mode))

    if not bases:
        return finish(PadReadBatch.failed(
            FailureReason.BASELINE_UNREADABLE, "기준 이미지에서 패드를 판독하지 못했다"))

    readings = _analyze_all(reading_bgr, pad_tone, cfg, spec, mode)
    if not readings:
        return finish(PadReadBatch.failed(
            FailureReason.PAD_NOT_FOUND, "판독 이미지에서 패드를 판독하지 못했다"))

    # 후보를 받았으면 그 안에서 배정한다. 기준 사진 쪽도 같이 배정해야
    # 짝짓기가 성립한다 - 한쪽만 배정하면 번호가 서로 다른 축이 된다.
    if expected_ids:
        assign_ids(readings, list(expected_ids), cfg.point_id)
        assign_ids(bases, list(expected_ids), cfg.point_id)

    pads = [
        _compare(reading, _match(reading, readings, bases), cfg, spec, visualize)
        for reading in readings
    ]
    return finish(PadReadBatch(success=any(p.success for p in pads), pads=pads))


def _contrast(analysis: _Analysis) -> str:
    """앵커 대비를 사유 문구에 적을 짧은 표기."""
    value = analysis.anchor_contrast
    return "측정 못함" if value is None else f"{value:+.1f}"


def _match(
    reading: _Analysis, readings: list[_Analysis], bases: list[_Analysis]
) -> _Analysis | None:
    """판독 패드의 짝이 되는 기준 패드. 번호로 맞춘다.

    양쪽에 패드가 하나씩뿐이면 번호를 보지 않고 짝으로 본다. 번호 판독이 가끔
    틀리는데, 후보가 하나뿐이면 그것 말고 짝이 될 것이 없기 때문이다.

    **하나라도 여러 개면 번호가 맞는 것만 짝짓는다.** 소거법으로 남은 것끼리
    맺지 않는다 — 패드를 오검출했을 때 그 가짜 패드가 멀쩡한 기준을 차지해
    조용히 틀린 값을 내기 때문이다. 짝을 못 찾으면 실패로 남기는 편이 낫다.

    같은 번호의 기준이 여러 장에 들어 있으면 먼저 온 것을 쓴다.
    """
    if len(readings) == 1 and len(bases) == 1:
        return bases[0]
    if reading.point_id is None:
        return None
    return next((b for b in bases if b.point_id == reading.point_id), None)


def _compare(
    reading: _Analysis,
    base: _Analysis | None,
    cfg: Config,
    spec: PadSpec,
    visualize: bool,
) -> PadReadResult:
    """판독 패드 하나를 짝지어진 기준 패드와 견준다."""
    partial: dict[str, Any] = {
        "quality": reading.quality,
        "rotation_deg": reading.rotation_deg,
        "rotation_margin": reading.rotation_margin,
        "point_id": reading.point_id,
        "point_id_raw": reading.point_id_raw,
        "point_id_status": reading.point_id_status,
        "point_id_confidence": reading.point_id_confidence,
        # 실패로 끝나는 길에도 같이 내보낸다. 잔차가 필요한 때가 바로 실패했을
        # 때다 - 사유 이름만 받으면 좌표가 어긋난 것인지 사진이 나쁜 것인지
        # 밖에서 가릴 수 없다.
        "verification": Verification(
            border_fit_error=reading.border_fit_error,
            anchor_contrast=reading.anchor_contrast,
            point_id_agrees=(
                None
                if reading.point_id is None or reading.point_id_raw is None
                else reading.point_id == reading.point_id_raw
            ),
        ),
    }

    if base is None:
        found = reading.point_id or "읽지 못함"
        return PadReadResult.failed(
            FailureReason.BASELINE_PAD_MISSING,
            f"기준 이미지에 같은 번호의 패드가 없다 (번호 {found})",
            **partial,
        )

    if reading.pad_type != base.pad_type:
        return PadReadResult.failed(
            FailureReason.PAD_TYPE_MISMATCH,
            f"판독은 {reading.pad_type}, 기준은 {base.pad_type} 로 판별됐다",
            **partial,
        )

    # 두 사진의 패드 크기가 크게 다르면 촬영 위치가 달라진 것이다.
    limit = cfg.quality.max_pad_size_diff_ratio
    reading_size = reading.quality.pad_size_px or 0.0
    baseline_size = base.quality.pad_size_px or 0.0
    largest = max(reading_size, baseline_size)
    size_diff = abs(reading_size - baseline_size) / largest if largest > 0 else 0.0
    if limit is not None and size_diff > limit:
        return PadReadResult.failed(
            FailureReason.PAD_SIZE_MISMATCH,
            f"패드 크기 차이 {size_diff:.3f} > 임계 {limit:.3f} "
            f"(판독 {reading_size:.0f}px, 기준 {baseline_size:.0f}px)",
            **partial,
        )

    scores, blobs, uniform_diff = compute_scores(
        reading.dust, base.dust, cfg.dust, cfg.score
    )

    measurable = reading.dust.measurable & base.dust.measurable
    if not measurable.any():
        return PadReadResult.failed(
            FailureReason.NO_MEASURABLE_AREA,
            f"제외 후 남은 영역이 없다 ({reading.dust.excluded_pixels})",
            excluded_px=reading.dust.excluded_pixels,
            **partial,
        )

    # reflectance 는 정면 보정 이미지 전체(예: 1120x1120) 이고 measurable 은
    # 여백만 잘라낸 크기다 - origin 과 measurable 의 모양으로 같은 자리를 자른다.
    ox, oy = reading.dust.origin
    mh, mw = measurable.shape
    optical_density = compute_optical_density(
        reading.reflectance[oy : oy + mh, ox : ox + mw],
        base.reflectance[oy : oy + mh, ox : ox + mw],
        reading.normalization_scale,
        base.normalization_scale,
        measurable,
    )
    optical_density.pad_scale = (
        (cfg.pad_size_px / reading_size) if reading_size > 0 else None
    )

    chroma_normalization = ChromaNormalizationInfo()
    chroma_score = None
    luma_dark_score = None
    luma_light_score = None
    chroma_diagnostics = ChromaDiagnostics()

    if reading.pad_type == "chroma":
        failure = reading.chroma_failure or base.chroma_failure
        if failure is not None:
            # 앵커 실측값을 사유에 같이 적는다. "성립하지 않는다" 만으로는
            # 좌표가 어긋난 것인지 사진이 나쁜 것인지 가릴 수 없다 - 대비가
            # 음수면 앵커 자리를 흑백 반대로 짚고 있다는 뜻이다.
            return PadReadResult.failed(
                failure,
                "유채색 패드의 앵커 정규화가 성립하지 않는다 "
                f"(앵커 대비 판독 {_contrast(reading)}, 기준 {_contrast(base)})",
                chroma_normalization=ChromaNormalizationInfo(
                    success=False, failure_reason=failure.value
                ),
                chroma_diagnostics=ChromaDiagnostics(
                    anchor_values={
                        "reading": reading.chroma_anchor_values,
                        "baseline": base.chroma_anchor_values,
                    }
                ),
                **partial,
            )

        reading_region = reading.chroma_reflectance[oy : oy + mh, ox : ox + mw]
        base_region = base.chroma_reflectance[oy : oy + mh, ox : ox + mw]

        reading_luma = luma_of(reading_region)
        base_luma = luma_of(base_region)
        reading_sat = saturation_of(reading_region)
        base_sat = saturation_of(base_region)

        # 채도가 줄어든 양이 오염량. 부호 그대로(임계값 없이) 합산한다.
        chroma_score = field_score(base_sat - reading_sat, measurable)

        # 명도는 흑색 분진(감소)과 백색 분진(증가)이 서로 상쇄되므로 방향을
        # 갈라 각각 낸다. 분모(N)는 두 방향 모두 노출 영역 전체 픽셀 수로
        # 같다 - 한쪽 방향의 국소 변화라도 전체 면적 대비 등가 깊이를 낸다.
        luma_diff = base_luma - reading_luma  # 양수=어두워짐
        luma_dark_score = field_score(np.where(luma_diff > 0, luma_diff, 0.0), measurable)
        luma_light_score = field_score(np.where(luma_diff < 0, -luma_diff, 0.0), measurable)

        chroma_normalization = ChromaNormalizationInfo(success=True)
        chroma_diagnostics = ChromaDiagnostics(
            roi_mean_reading=channel_means(reading_region, measurable),
            roi_mean_baseline=channel_means(base_region, measurable),
            anchor_values={
                "reading": reading.chroma_anchor_values,
                "baseline": base.chroma_anchor_values,
            },
            pad_scale=optical_density.pad_scale,
            clipped_ratio=clipped_ratio(
                reading.rectified[oy : oy + mh, ox : ox + mw]
            ),
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
        optical_density=optical_density,
        pad_type=reading.pad_type,
        chroma_normalization=chroma_normalization,
        **({"chroma": chroma_score} if chroma_score is not None else {}),
        **({"luma_dark": luma_dark_score} if luma_dark_score is not None else {}),
        **({"luma_light": luma_light_score} if luma_light_score is not None else {}),
        chroma_diagnostics=chroma_diagnostics,
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

    return result


def read_pad(
    image: Any,
    baseline: Any,
    pad_tone: str,
    config: Config | None = None,
    overrides: Mapping[str, Any] | None = None,
    visualize: bool = False,
    expected_ids: list[str] | None = None,
    mode: str = "auto",
) -> PadReadResult:
    """가장 크게 찍힌 패드 하나만 돌려준다.

    한 장에 패드가 하나만 찍히는 흔한 경우를 위한 지름길이다. 여러 개가 찍힐
    수 있는 사진이면 ``read_pads`` 를 쓴다.
    """
    return read_pads(
        image, baseline, pad_tone, config, overrides, visualize, expected_ids, mode
    ).first

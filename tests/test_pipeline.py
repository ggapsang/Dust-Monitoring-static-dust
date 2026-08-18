"""판독 파이프라인 검증.

합성 이미지로 다음을 확인한다.

- 촬영 각도와 거리를 바꿔도 스코어가 한 범위로 수렴하는지
- 조명·노출·블랙레벨을 바꿔도 스코어 변동이 억제되는지
- 도포량이 늘면 스코어가 단조 증가하는지
- localized 뭉침과 균일 침착을 구획 값 산포가 구분하는지
- 위 항목이 흑·백 두 패드에서 각각 성립하는지

합성의 한계를 분명히 해 둔다. 여기 통과한다고 실촬영에서 통과하는 것이
아니다. 합성은 ``padtools.synth`` 가 주입한 모델을 그대로 되돌려줄 뿐이라,
테두리 조명 추정이 실제 정밀도를 내는지 같은 것은 실촬영으로만 판정된다.
"""

from __future__ import annotations

import numpy as np
import pytest

from padreader import FailureReason, TargetIdStatus, read_pad, spec
from padtools.synth import CaptureParams, Clump, expected_soiling, synthesize, vary

# 앵커가 보호된 규격을 기준으로 검증한다. 노출 앵커나 앵커 없는 규격은
# 조도 기준이 잉크 하나뿐이라 블랙레벨을 소거하지 못하는데, 그 한계는
# test_black_level_sensitivity_by_reference 가 따로 다룬다.
SPEC_NAME = "v2_protected"
SPEC = spec.SPECS[SPEC_NAME]

BASE = CaptureParams(pad_fill=0.55, black_level=10, gain=0.95, noise_sigma=0.8, seed=11)

TONES = ("white", "black")


def baseline_image(tone: str, params: CaptureParams = BASE):
    """기준 사진. 판독 사진과 같은 촬영 조건에서 분진만 없는 상태."""
    image, _ = synthesize(SPEC, tone, vary(params, dust_coverage=0.0, clumps=()))
    return image


def run(tone: str, params: CaptureParams, baseline=None, **overrides):
    image, _ = synthesize(SPEC, tone, params)
    merged = {"spec": SPEC_NAME}
    merged.update(overrides)
    base = baseline if baseline is not None else baseline_image(tone, params)
    return read_pad(image, base, tone, overrides=merged)


@pytest.fixture(params=TONES)
def tone(request) -> str:
    return request.param


def test_clean_pad_scores_near_zero(tone: str) -> None:
    result = run(tone, BASE)
    assert result.success, result.failure_detail
    assert abs(result.dust_score) < 0.02, result.dust_score


def test_absolute_accuracy(tone: str) -> None:
    """알려진 도포량에 대해 절대 오차가 작은지.

    앵커 2점 정규화가 성립하면 스코어는 곧 앵커 기준 피복률 추정이 된다.
    """
    for coverage in (0.05, 0.2, 0.5):
        result = run(tone, vary(BASE, dust_coverage=coverage))
        assert result.success, result.failure_detail
        assert abs(result.dust_score - expected_soiling(tone, coverage)) < 0.02, (
            f"{tone} cov={coverage}: {result.dust_score}"
        )


def test_score_increases_monotonically_with_coverage(tone: str) -> None:
    scores = []
    for coverage in (0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5):
        result = run(tone, vary(BASE, dust_coverage=coverage))
        assert result.success, result.failure_detail
        scores.append(result.dust_score)

    diffs = np.diff(scores)
    assert (diffs > 0).all(), f"{tone}: 단조 증가가 아니다 {scores}"


def test_score_converges_across_viewpoints(tone: str) -> None:
    """각도와 거리를 바꿔도 같은 값으로 수렴하는지."""
    params = vary(BASE, dust_coverage=0.2)
    scores = []
    for tilt, pan, roll, fill in (
        (0, 0, 0, 0.55),
        (12, 30, 5, 0.45),
        (25, 150, -8, 0.6),
        (35, 250, 12, 0.35),
        (40, 70, -3, 0.65),
    ):
        result = run(
            tone,
            vary(params, tilt_deg=tilt, pan_deg=pan, roll_deg=roll, pad_fill=fill),
        )
        assert result.success, f"tilt={tilt} fill={fill}: {result.failure_detail}"
        scores.append(result.dust_score)

    assert max(scores) - min(scores) < 0.03, f"{tone}: 시점별 편차 {scores}"


def test_score_resists_illumination_and_exposure(tone: str) -> None:
    """조명 세기·기울기, 게인, 블랙레벨을 바꿔도 값이 버티는지.

    조합은 밝은 쪽이 포화되지 않는 범위로 잡았다. 포화된 이미지는 판독
    대상이 아니라 걸러낼 대상이고, 그쪽은 별도 테스트가 다룬다.

    세로 방향 기울기(direction 90, 45)가 특히 중요하다. 앵커가 전부 상단
    밴드에 있어 반사율 척도가 그 자리의 조도에 고정되므로, 기울기 보정이
    패드 평균이 아니라 앵커 자리를 1 로 잡지 않으면 여기서 어긋난다.
    """
    params = vary(BASE, dust_coverage=0.2)
    scores = []
    for gradient, direction, gain, black in (
        (0.0, 0, 1.0, 0),
        (0.15, 0, 0.85, 8),
        (0.3, 90, 0.75, 18),
        (0.3, 210, 0.6, 25),
        (0.45, 45, 0.62, 12),
    ):
        result = run(
            tone,
            vary(
                params,
                light_gradient=gradient,
                light_direction_deg=direction,
                gain=gain,
                black_level=black,
            ),
        )
        assert result.success, result.failure_detail
        assert result.quality.saturated_bright_ratio == 0.0, "노출 범위를 벗어난 조합"
        scores.append(result.dust_score)

    assert max(scores) - min(scores) < 0.03, f"{tone}: 조명·노출별 편차 {scores}"


def test_overexposure_is_visible_in_quality(tone: str) -> None:
    """과노출은 포화율로 드러나고 게이트로 막을 수 있어야 한다.

    밝은 쪽이 잘리면 백색 앵커까지 255 에 붙어 정규화 척도가 무너진다.
    스코어를 조용히 내놓는 대신 걸러내야 하는 조건이다.
    """
    blown = vary(BASE, dust_coverage=0.2, light_gradient=0.3, gain=1.3, black_level=18)
    good = baseline_image(tone)

    measured = run(tone, blown, baseline=good)
    assert measured.quality.saturated_bright_ratio is not None
    assert measured.quality.saturated_bright_ratio > 0.001, (
        measured.quality.saturated_bright_ratio
    )

    gated = run(tone, blown, baseline=good, quality={"max_saturated_bright_ratio": 0.001})
    assert not gated.success
    assert gated.failure_reason is FailureReason.QUALITY_SATURATION


def test_dispersion_separates_clumped_from_uniform(tone: str) -> None:
    """같은 총 침착량이라도 localized 뭉침과 균일 침착이 구분되는지.

    ``p90 - p50`` 이 갈라져야 한다. 균일하면 모든 구획이 같이 움직여 거의
    0 이고, 뭉치면 소수 구획만 튀어 크게 벌어진다.
    """
    uniform = run(tone, vary(BASE, dust_coverage=0.15))
    clumped = run(
        tone,
        vary(
            BASE,
            dust_coverage=0.0,
            clumps=(
                Clump(x=0.35, y=0.45, sigma=0.05, coverage=0.8),
                Clump(x=0.62, y=0.55, sigma=0.04, coverage=0.7),
            ),
        ),
    )
    assert uniform.success and clumped.success

    assert clumped.dispersion.p90_minus_p50 > uniform.dispersion.p90_minus_p50 * 5, (
        f"{tone}: 균일 {uniform.dispersion.p90_minus_p50:.4f} vs "
        f"뭉침 {clumped.dispersion.p90_minus_p50:.4f}"
    )
    assert clumped.dispersion.iqr > uniform.dispersion.iqr


def test_rotation_is_recovered(tone: str) -> None:
    """네 방향으로 붙여도 같은 값을 읽는지."""
    scores = []
    for quarter in range(4):
        result = run(tone, vary(BASE, dust_coverage=0.2, quarter_turns=quarter))
        assert result.success, f"quarter={quarter}: {result.failure_detail}"
        assert result.rotation_deg == (-quarter * 90) % 360
        assert result.rotation_margin > 0.5
        scores.append(result.dust_score)

    assert max(scores) - min(scores) < 0.02, scores


def test_target_id_is_read(tone: str) -> None:
    for target in ("1078", "42", "9310"):
        image, _ = synthesize(SPEC, tone, BASE, target_id=target)
        base, _ = synthesize(SPEC, tone, BASE, target_id=target)
        result = read_pad(image, base, tone, overrides={"spec": SPEC_NAME})
        assert result.success
        assert result.target_id_status is TargetIdStatus.OK, result.target_id_confidence
        assert result.target_id == target


def test_target_id_failure_does_not_fail_the_read(tone: str) -> None:
    """ID 를 못 읽어도 분진 스코어는 유효해야 한다."""
    image, _ = synthesize(SPEC, tone, BASE, target_id="")
    result = read_pad(image, image, tone, overrides={"spec": SPEC_NAME})
    assert result.success
    assert result.target_id_status is TargetIdStatus.FAILED


def test_is_deterministic(tone: str) -> None:
    """같은 입력에 같은 출력. 모듈이 상태를 갖지 않는다는 뜻이다."""
    image, _ = synthesize(SPEC, tone, vary(BASE, dust_coverage=0.12))
    base = baseline_image(tone)
    first = read_pad(image, base, tone, overrides={"spec": SPEC_NAME})
    second = read_pad(image, base, tone, overrides={"spec": SPEC_NAME})
    assert first.dust_score == second.dust_score
    assert [c.value for c in first.cells] == [c.value for c in second.cells]


def test_line_contrast_falls_with_coverage(tone: str) -> None:
    """선군 대비가 오염이 늘수록 떨어지는지. 네 단계 모두 산출되는지."""
    clean = run(tone, BASE)
    dirty = run(tone, vary(BASE, dust_coverage=0.4))
    assert len(clean.line_contrasts) == len(SPEC.line_bars)
    assert all(c.contrast is not None for c in clean.line_contrasts)

    clean_mean = np.mean([c.contrast for c in clean.line_contrasts])
    dirty_mean = np.mean([c.contrast for c in dirty.line_contrasts])
    assert dirty_mean < clean_mean, f"{tone}: {clean_mean} -> {dirty_mean}"


def test_grid_shape_is_configurable(tone: str) -> None:
    result = run(tone, BASE, grid={"rows": 4, "cols": 4})
    assert result.success
    assert result.grid_shape == (4, 4)
    assert len(result.cells) == 16


def test_score_statistic_is_configurable(tone: str) -> None:
    params = vary(
        BASE, clumps=(Clump(x=0.3, y=0.5, sigma=0.05, coverage=0.8),)
    )
    p50 = run(tone, params, score={"statistic": "p50"})
    p90 = run(tone, params, score={"statistic": "p90"})
    maximum = run(tone, params, score={"statistic": "max"})

    # localized 오염이라 대표값을 올릴수록 커져야 한다. 평균을 쓰면 이 차이가
    # 희석되어 사라진다.
    assert p50.dust_score < p90.dust_score < maximum.dust_score


def test_quality_gate_rejects_blurred_image(tone: str) -> None:
    sharp = run(tone, BASE)
    assert sharp.success
    assert sharp.quality.edge_rise_ratio is not None

    blurred_params = vary(BASE, blur_sigma=9.0)
    good = baseline_image(tone)
    measured = run(tone, blurred_params, baseline=good)
    limit = sharp.quality.edge_rise_ratio * 2.0

    gated = run(
        tone, blurred_params, baseline=good, quality={"max_edge_rise_ratio": limit}
    )
    assert measured.quality.edge_rise_ratio > limit, measured.quality.edge_rise_ratio
    assert not gated.success
    assert gated.failure_reason is FailureReason.QUALITY_SHARPNESS


def test_quality_gate_rejects_steep_angle(tone: str) -> None:
    steep = vary(BASE, tilt_deg=40, pan_deg=20)
    good = baseline_image(tone)
    ungated = run(tone, steep, baseline=good)
    assert ungated.quality.tilt_deg is not None and ungated.quality.tilt_deg > 10

    gated = run(tone, steep, baseline=good, quality={"max_tilt_deg": 5.0})
    assert not gated.success
    assert gated.failure_reason is FailureReason.QUALITY_ANGLE


def test_baseline_failure_is_reported_as_such(tone: str) -> None:
    """기준 사진을 못 읽으면 그 사실이 사유로 나와야 한다.

    판독 사진이 아무리 멀쩡해도 견줄 대상이 없으면 오염량을 낼 수 없다.
    판독 사진 탓으로 보이면 엉뚱한 곳을 고치게 된다.
    """
    blank = np.full((600, 800, 3), 120, np.uint8)
    image, _ = synthesize(SPEC, tone, vary(BASE, dust_coverage=0.2))
    result = read_pad(image, blank, tone, overrides={"spec": SPEC_NAME})

    assert not result.success
    assert result.failure_reason is FailureReason.BASELINE_UNREADABLE
    assert "pad_not_found" in (result.failure_detail or "")


def test_same_photo_twice_scores_zero(tone: str) -> None:
    """같은 사진을 기준과 판독으로 넣으면 오염량이 정확히 0 이어야 한다.

    두 장에 똑같은 처리가 적용되는지를 가장 직접적으로 확인하는 방법이다.
    """
    image, _ = synthesize(SPEC, tone, vary(BASE, dust_coverage=0.3))
    result = read_pad(image, image, tone, overrides={"spec": SPEC_NAME})

    assert result.success, result.failure_detail
    assert result.dust_score == 0.0
    assert all(c.value == 0.0 for c in result.cells if c.excluded is None)


def test_cells_carry_both_sides(tone: str) -> None:
    """칸마다 판독값·기준값·그 차이가 함께 나와야 한다."""
    result = run(tone, vary(BASE, dust_coverage=0.2))
    assert result.success

    for cell in result.cells:
        if cell.excluded is not None:
            continue
        assert cell.reading is not None and cell.baseline is not None
        assert cell.value == pytest.approx(cell.reading - cell.baseline, abs=1e-9)


def test_missing_pad_is_reported(tone: str) -> None:
    empty = np.full((600, 800, 3), 120, np.uint8)
    result = read_pad(empty, baseline_image(tone), tone, overrides={"spec": SPEC_NAME})
    assert not result.success
    assert result.failure_reason is FailureReason.PAD_NOT_FOUND


def test_invalid_tone_is_rejected() -> None:
    blank = np.zeros((10, 10, 3), np.uint8)
    result = read_pad(blank, blank, "gray")
    assert not result.success
    assert result.failure_reason is FailureReason.INVALID_IMAGE


def test_result_serializes_without_images(tone: str) -> None:
    import json

    result = run(tone, vary(BASE, dust_coverage=0.1))
    payload = result.to_dict()
    json.dumps(payload)
    assert "rectified" not in payload and "overlay" not in payload
    assert payload["grid_shape"] == [8, 11]


def test_visualization_is_optional(tone: str) -> None:
    image, _ = synthesize(SPEC, tone, BASE)
    base = baseline_image(tone)
    plain = read_pad(image, base, tone, overrides={"spec": SPEC_NAME})
    assert plain.rectified is None and plain.overlay is None

    drawn = read_pad(image, base, tone, overrides={"spec": SPEC_NAME}, visualize=True)
    assert drawn.rectified is not None and drawn.overlay is not None
    assert drawn.overlay.shape == drawn.rectified.shape


def test_processing_time_budget(tone: str) -> None:
    """1장 1초 이내 목표. 여유를 두되 자릿수가 틀어지면 잡는다."""
    result = run(tone, vary(BASE, dust_coverage=0.1))
    assert result.success
    assert result.elapsed_ms is not None and result.elapsed_ms < 1000.0


@pytest.mark.parametrize("tone", TONES)
def test_black_level_sensitivity_by_reference(tone: str) -> None:
    """조도 기준을 무엇으로 잡느냐가 블랙레벨 민감도를 가른다.

    관측값은 ``B0 + g*E*rho`` 다. 앵커 2점은 ``B0`` 와 ``g*E`` 를 함께
    소거하지만, 잉크 하나로 나누는 방식은 ``B0`` 를 남긴다. 그 영향은 기준면
    반사율이 낮을수록 커지므로, 기준이 흑색 잉크인 백색 바탕 패드에서 가장
    심하다.

    이 테스트는 성능을 요구하는 것이 아니라 **한계를 고정**한다. 노출 앵커
    패드로 절대값을 읽으려 하면 여기서 막힌다.
    """
    black_levels = (0, 8, 16, 25)

    protected = [
        run(tone, vary(BASE, dust_coverage=0.2, black_level=b)).dust_score
        for b in black_levels
    ]
    assert max(protected) - min(protected) < 0.005, protected

    exposed = []
    for b in black_levels:
        image, _ = synthesize(spec.V2, tone, vary(BASE, dust_coverage=0.2, black_level=b))
        base, _ = synthesize(spec.V2, tone, vary(BASE, dust_coverage=0.0, black_level=b))
        result = read_pad(image, base, tone, overrides={"spec": "v2"})
        assert result.success, result.failure_detail
        assert result.normalization.method == "border_ratio"
        exposed.append(result.dust_score)

    spread = max(exposed) - min(exposed)
    if tone == "white":
        # 실제 분진 신호 폭(0.2 피복 ~ 0.2)에 견줄 만큼 흔들린다.
        assert spread > 0.1, f"백색 패드에서 블랙레벨 영향이 사라졌다: {exposed}"
    else:
        # 기준이 백색 잉크라 훨씬 견딘다. 그래도 앵커 쪽이 낫다.
        assert spread < 0.1, exposed
    assert spread > (max(protected) - min(protected))

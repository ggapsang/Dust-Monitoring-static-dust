"""``spec.py`` 의 상수가 실제 도안(``assets/`` 샘플 PNG)과 맞는지 검증한다.

생성기의 폰트까지 똑같이 재현할 수는 없으므로 이미지 전체 비교는 하지
않는다. 대신 샘플을 다시 스캔해 **기하**를 뽑고 상수와 대조한다. 규격
숫자가 어긋나면 여기서 잡힌다.

가장 중요한 검증은 ``test_margin_contains_no_print`` 다 — 측정 여백을
'테두리 안쪽 정사각'이 아니라 '인쇄물이 없는 중간 밴드'로 정의한 근거가
바로 이것이고, 이게 깨지면 격자에 인쇄물이 섞여 들어간다.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from padreader import spec

# 도안은 판독 모듈 밖에 있다. padlab 도 같은 도안을 참조하므로 저장소
# 루트에 둔다 - reader/ 안으로 옮기면 두 벌이 생긴다.
ASSETS = Path(__file__).resolve().parents[2] / "assets"

# 샘플 PNG. 도안은 관측 포인트 번호마다 한 장씩 있고 번호만 다르므로,
# 기하를 검증하는 이 파일은 그중 한 벌만 본다.
SAMPLE_POINT_ID = "1078"
SAMPLES = {
    "white": ASSETS / f"marker_sample_background_white_{SAMPLE_POINT_ID}.png",
    "black": ASSETS / f"marker_sample_background_black_{SAMPLE_POINT_ID}.png",
}

TOL_PX = 3
"""허용 오차. 샘플 렌더의 안티에일리어싱 때문에 좌우가 1px 정도 어긋나 있다."""


def ink_mask(path: Path, tone: str) -> np.ndarray:
    """인쇄색 화소를 True 로 하는 마스크.

    백색 바탕 패드는 인쇄가 어둡고, 흑색 바탕 패드는 밝다. 톤에 따라
    극성을 뒤집어 이후 스캔 로직을 하나로 통일한다 — 판독 파이프라인이
    쓰는 방식과 같다.
    """
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    assert img is not None, f"샘플을 읽을 수 없다: {path}"
    return img < 128 if tone == "white" else img > 128


def runs(flags: np.ndarray) -> list[tuple[int, int]]:
    """True 구간을 반열린 (start, end) 목록으로."""
    idx = np.flatnonzero(np.diff(np.concatenate(([0], flags.view(np.int8), [0]))))
    return list(zip(idx[0::2].tolist(), idx[1::2].tolist()))


@pytest.fixture(params=sorted(SAMPLES))
def tone(request) -> str:
    return request.param


@pytest.fixture
def mask(tone: str) -> np.ndarray:
    return ink_mask(SAMPLES[tone], tone)


def to_canvas(norm: float) -> float:
    """정규화 좌표를 샘플 캔버스 픽셀로 (spec.from_canvas 의 역)."""
    return norm * spec.SAMPLE_PAD_SIZE + spec.SAMPLE_PAD_ORIGIN


def test_sample_canvas_matches_spec_constants(mask: np.ndarray) -> None:
    """샘플이 spec 이 가정하는 캔버스 규격인지."""
    assert mask.shape == (spec.SAMPLE_CANVAS, spec.SAMPLE_CANVAS)


def test_pad_outer_bounds(mask: np.ndarray) -> None:
    """패드 외곽이 캔버스 40..1160 에 있는지. 정규화의 기준점이다."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    for got, name in ((rows, "row"), (cols, "col")):
        assert abs(int(got[0]) - spec.SAMPLE_PAD_ORIGIN) <= TOL_PX, name
        end = spec.SAMPLE_PAD_ORIGIN + spec.SAMPLE_PAD_SIZE
        assert abs(int(got[-1]) + 1 - end) <= TOL_PX, name


def test_border_thickness(mask: np.ndarray) -> None:
    """중앙 행에서 테두리 두께를 재 spec 과 대조."""
    center = mask[spec.SAMPLE_CANVAS // 2]
    segments = runs(center)
    assert len(segments) == 2, f"중앙 행에 테두리 두 조각만 있어야 한다: {segments}"

    expected = spec.BORDER_THICKNESS * spec.SAMPLE_PAD_SIZE
    left, right = segments
    assert abs((left[1] - left[0]) - expected) <= TOL_PX
    assert abs((right[1] - right[0]) - expected) <= TOL_PX


def corner_fill(mask: np.ndarray) -> dict[str, float]:
    """네 모서리 블록 자리가 인쇄색으로 얼마나 차 있는지."""
    filled = {}
    for name, rect in spec.LEGACY.corner_blocks.items():
        x0, y0, x1, y1 = (int(round(to_canvas(v))) for v in (rect.x0, rect.y0, rect.x1, rect.y1))
        # 경계 오차를 피하려 안쪽으로 조금 물러나 본다.
        pad = TOL_PX + 2
        patch = mask[y0 + pad : y1 - pad, x0 + pad : x1 - pad]
        assert patch.size > 0, name
        filled[name] = float(patch.mean())
    return filled


def test_three_corner_blocks_are_filled(mask: np.ndarray) -> None:
    """TL/TR/BL 블록이 인쇄색으로 차 있는지."""
    filled = corner_fill(mask)
    for name in ("tl", "tr", "bl"):
        assert filled[name] > 0.95, f"{name} 블록이 차 있어야 한다: {filled}"
    assert spec.LEGACY.empty_corner == "br"


def test_legacy_br_slot_is_polluted_by_line_group(mask: np.ndarray) -> None:
    """legacy 도안의 알려진 결함을 고정한다.

    선군이 x=1065 까지 뻗어 BR 모서리 블록 자리(x 999..1072)를 관통하는
    바람에, 비어 있어야 할 BR 이 절반 넘게 차 있다. 회전 판정은 여전히
    되지만 마진이 절반으로 깎인다 — 실촬영 노이즈에서 회전이 뒤집힐 여지다.

    도안이 고쳐지면 이 테스트가 실패하면서 알려준다. 그때는 v2 로 옮기면 된다.
    """
    filled = corner_fill(mask)
    assert 0.3 < filled["br"] < 0.7, f"BR 오염 정도가 달라졌다: {filled}"
    assert min(filled[n] for n in ("tl", "tr", "bl")) - filled["br"] > 0.3, (
        f"그래도 판정은 되어야 한다: {filled}"
    )
    assert not spec.LEGACY.line_group_clears_corner_slots


def test_v2_line_group_clears_corner_slots() -> None:
    """v2 는 선군이 모서리 블록 자리를 침범하지 않는다."""
    assert spec.V2.line_group_clears_corner_slots
    assert spec.V2.line_group_x1 < spec.V2.corner_blocks["br"].x0


def test_line_group_bars(mask: np.ndarray) -> None:
    """선군 4단의 위치와 굵기가 spec 과 맞는지."""
    x = spec.SAMPLE_CANVAS // 2
    column = mask[:, x].copy()
    # 테두리 안쪽만 본다. 아래쪽 테두리가 5번째 구간으로 섞여 들어온다.
    inner = spec.LEGACY.inner
    column[: int(round(to_canvas(spec.LEGACY.margin_raw.y1))) - 20] = False
    column[int(round(to_canvas(inner.y1))) :] = False
    segments = runs(column)

    assert len(segments) == len(spec.LINE_BARS), f"선군 4단이어야 한다: {segments}"
    for (got_y0, got_y1), bar in zip(segments, spec.LEGACY.line_bars):
        assert abs(got_y0 - to_canvas(bar.y0)) <= TOL_PX
        assert abs((got_y1 - got_y0) - bar.thickness * spec.SAMPLE_PAD_SIZE) <= TOL_PX


def test_point_id_box_contains_digits(mask: np.ndarray) -> None:
    """POINT_ID 박스가 숫자를 전부 감싸는지. POINT_ID 판독 ROI 다."""
    box = spec.LEGACY.point_id_box
    x0, y0, x1, y1 = (int(round(to_canvas(v))) for v in (box.x0, box.y0, box.x1, box.y1))

    # 박스 안에 숫자가 있고
    assert mask[y0:y1, x0:x1].any()

    # 박스 바깥 상단 밴드에는 (모서리 블록을 빼면) 숫자가 없어야 한다.
    band = mask.copy()
    band[:, x0:x1] = False
    blocks = spec.LEGACY.corner_blocks
    for rect in blocks.values():
        bx0, by0, bx1, by1 = (int(round(to_canvas(v))) for v in (rect.x0, rect.y0, rect.x1, rect.y1))
        band[by0 - TOL_PX : by1 + TOL_PX, bx0 - TOL_PX : bx1 + TOL_PX] = False
    inner = spec.LEGACY.inner
    ix0, ix1 = (int(round(to_canvas(v))) for v in (inner.x0, inner.x1))
    leaked = band[y0:y1, ix0:ix1]
    assert not leaked.any(), "POINT_ID 박스 밖 상단 밴드에 인쇄물이 남았다"


def test_margin_contains_no_print(mask: np.ndarray) -> None:
    """측정 여백에 인쇄 화소가 하나도 없는지.

    이 모듈은 여백을 마스킹하지 않는다. 인쇄물이 상단·하단 밴드에만
    있고 중간 밴드가 통째로 비어 있다는 사실에 기대고 있기 때문이다. 도안이
    바뀌어 여백에 인쇄물이 들어오면 모든 구획 값이 오염되므로 여기서 막는다.
    """
    m = spec.LEGACY.margin
    x0, y0, x1, y1 = (int(round(to_canvas(v))) for v in (m.x0, m.y0, m.x1, m.y1))
    region = mask[y0:y1, x0:x1]
    assert region.size > 0
    assert not region.any(), (
        f"여백에 인쇄 화소 {int(region.sum())}개가 있다. "
        f"여백 범위 canvas x[{x0},{x1}) y[{y0},{y1})"
    )


@pytest.mark.parametrize("spec_obj", [spec.LEGACY, spec.V2], ids=lambda s: s.name)
def test_print_elements_do_not_enter_margin(spec_obj: spec.PadSpec) -> None:
    """인쇄 요소가 측정 여백을 침범하지 않는지 (기하 불변식).

    여백을 마스킹 없이 격자로 나누는 근거다. 규격을 손대다 요소를
    몇 픽셀만 밀어도 글리프가 여백에 새어 들어가 구획 값이 오염되므로,
    이미지가 아니라 좌표 수준에서 막는다.
    """
    margin = spec_obj.margin_raw
    for name, rect in spec_obj.print_element_rects().items():
        overlap_x = min(rect.x1, margin.x1) - max(rect.x0, margin.x0)
        overlap_y = min(rect.y1, margin.y1) - max(rect.y0, margin.y0)
        assert overlap_x <= 0 or overlap_y <= 0, (
            f"{spec_obj.name}: {name} {rect} 가 여백 {margin} 을 침범한다"
        )


@pytest.mark.parametrize("spec_obj", [spec.LEGACY, spec.V2], ids=lambda s: s.name)
def test_print_elements_stay_inside_border(spec_obj: spec.PadSpec) -> None:
    """인쇄 요소가 테두리를 물지 않는지. 물면 조도 기준값이 오염된다."""
    inner = spec_obj.inner
    for name, rect in spec_obj.print_element_rects().items():
        assert rect.x0 >= inner.x0 and rect.y0 >= inner.y0, f"{name} {rect}"
        assert rect.x1 <= inner.x1 and rect.y1 <= inner.y1, f"{name} {rect}"


def test_margin_is_large_enough_to_be_useful() -> None:
    """여백이 패드 면적의 절반은 넘어야 측정 영역으로 쓸 만하다."""
    assert spec.LEGACY.margin.area > 0.5


def test_border_ring_rects_stay_inside_border(mask: np.ndarray) -> None:
    """조도 기준으로 쓰는 테두리 링 ROI 가 전부 인쇄색 위에 있는지.

    ROI 가 에지를 물면 기준 밝기가 바탕색 쪽으로 끌려가 정규화가 어긋난다.
    """
    for rect in spec.LEGACY.border_ring_rects():
        x0, y0, x1, y1 = (int(round(to_canvas(v))) for v in (rect.x0, rect.y0, rect.x1, rect.y1))
        patch = mask[y0:y1, x0:x1]
        assert patch.size > 0
        assert patch.mean() > 0.99, f"링 ROI 가 테두리를 벗어났다: {rect}"


def test_anchor_rects_do_not_collide(mask: np.ndarray) -> None:
    """v2 앵커 패치가 기존 인쇄물과 겹치지 않는지.

    앵커는 상단 밴드의 빈 공간에 들어가야 한다. legacy 도안에서 그 자리가
    실제로 비어 있음을 확인한다.
    """
    for rect in spec.V2.anchor_white + spec.V2.anchor_black:
        x0, y0, x1, y1 = (int(round(to_canvas(v))) for v in (rect.x0, rect.y0, rect.x1, rect.y1))
        patch = mask[y0:y1, x0:x1]
        assert patch.size > 0
        assert not patch.any(), f"앵커 자리에 기존 인쇄물이 있다: {rect}"


def test_anchor_rects_are_mirror_symmetric() -> None:
    """앵커가 좌우 대칭인지.

    대칭이라야 가로 방향 조명 기울기가 쌍 평균에서 상쇄된다.
    """
    for group in (spec.V2.anchor_white, spec.V2.anchor_black):
        assert len(group) == 2
        left, right = sorted(group, key=lambda r: r.x0)
        assert abs(left.x0 - (1.0 - right.x1)) < 1e-9
        assert abs(left.y0 - right.y0) < 1e-9


# ---------------------------------------------------------------------------
# v3 — 실제로 인쇄해 현장에 붙인 도안
#
# 위의 검증은 전부 이 저장소 생성기가 그리는 legacy/v2 도안을 본다. 현장에
# 붙은 패드는 그 계보가 아니라 ``assets/make_pad_dual_tones.py`` 와 그 유채색
# 변종이 그린 것이고, 두 계보의 좌표가 서로 달랐다. 그런데 그 어긋남을 아무도
# 재지 않아, 판독기가 v2 좌표로 실물을 재면서 유채색 판독이 전부 실패했다 -
# 앵커 흑백이 반대라 정규화의 분모가 음수가 됐다. 여기서 막는다.
# ---------------------------------------------------------------------------

V3_SAMPLES = {
    "white": ASSETS / "pad_dual_tones" / "pad_1083_white.png",
    "black": ASSETS / "pad_dual_tones" / "pad_1083_black.png",
    "magenta": ASSETS / "pad_dual_tones" / "pad_1088_magenta.png",
}

V3_QUIET = 0.125
"""실물 도안이 패드 바깥에 두른 흰 여백. 패드 한 변 대비 비율."""


def v3_frame(path: Path) -> tuple[np.ndarray, int, int]:
    """(BGR 이미지, 패드 외곽 원점 px, 패드 한 변 px)."""
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert img is not None, f"실물 도안을 읽을 수 없다: {path}"
    canvas = img.shape[1]
    pad = round(canvas / (1.0 + 2 * V3_QUIET))
    return img, (canvas - pad) // 2, pad


def v3_patch(path: Path, rect: spec.Rect) -> np.ndarray:
    img, origin, pad = v3_frame(path)
    x0, x1 = int(origin + rect.x0 * pad), int(origin + rect.x1 * pad)
    y0, y1 = int(origin + rect.y0 * pad), int(origin + rect.y1 * pad)
    patch = img[y0:y1, x0:x1]
    assert patch.size > 0
    return patch


@pytest.mark.parametrize("name", sorted(V3_SAMPLES))
def test_v3_anchor_rects_hit_the_right_shade(name: str) -> None:
    """``anchor_white`` 자리가 실제로 밝고 ``anchor_black`` 자리가 어두운지.

    **이것이 유채색 판독을 전부 실패시켰던 오류다.** 규격이 두 자리를 반대로
    알고 있으면 정규화의 분모 ``흰앵커 - 검은앵커`` 가 음수가 되어
    ``ANCHOR_SPAN_INVALID`` 로 떨어진다. 이름과 실물이 맞는지 여기서 잰다.

    마젠타 도안은 측정면만 유채색이고 앵커가 놓인 상단 밴드는 백색 패드와
    같으므로 ``V3`` 를 쓴다.
    """
    target = spec.V3_BLACK if name == "black" else spec.V3
    for rect in target.anchor_white:
        assert v3_patch(V3_SAMPLES[name], rect).mean() > 200, f"흰 앵커 자리가 밝지 않다: {rect}"
    for rect in target.anchor_black:
        assert v3_patch(V3_SAMPLES[name], rect).mean() < 55, f"검은 앵커 자리가 어둡지 않다: {rect}"


def test_v3_anchor_span_is_positive() -> None:
    """정규화의 분모가 양수인지. 위 검증의 결론을 판독기가 쓰는 형태로 다시 쓴 것이다."""
    for name, target in (("white", spec.V3), ("black", spec.V3_BLACK), ("magenta", spec.V3)):
        white = np.mean([v3_patch(V3_SAMPLES[name], r).mean() for r in target.anchor_white])
        black = np.mean([v3_patch(V3_SAMPLES[name], r).mean() for r in target.anchor_black])
        assert white - black > 100, f"{name}: 앵커 대비가 {white - black:.1f} 밖에 안 된다"


def test_v3_margin_is_exactly_the_measurement_area() -> None:
    """``margin_raw`` 가 인쇄된 측정면과 정확히 맞는지.

    유채색 검출은 눈에 보이는 측정면 덩어리에서 패드 외곽을 역산한다. 이
    사각형이 실물과 어긋나면 역산한 외곽이 그 비율만큼 밀려 앵커 자리가 통째로
    빗나간다.

    측정면만 유채색이므로 **채도가 있는 구간**을 세로·가로로 직접 훑어
    ``margin_raw`` 와 맞는지 잰다. '바깥은 흰 바탕' 으로 확인하지 않는다 -
    아래쪽은 흰 바탕이 아니라 선군이 곧바로 붙어 있다.
    """
    img, origin, pad = v3_frame(V3_SAMPLES["magenta"])
    rect = spec.V3.margin_raw

    field = img[origin : origin + pad, origin : origin + pad].astype(np.int16)
    mx = field.max(axis=2)
    chroma = (mx - field.min(axis=2)) > 40  # 무채색 인쇄는 세 채널이 같다

    middle = pad // 2
    top, bottom = runs(chroma[:, middle])[0]
    left, right = runs(chroma[middle, :])[0]

    for label, got, want in (
        ("위", top, rect.y0),
        ("아래", bottom, rect.y1),
        ("왼쪽", left, rect.x0),
        ("오른쪽", right, rect.x1),
    ):
        assert abs(got - want * pad) <= TOL_PX, (
            f"측정면 {label} 경계가 규격과 어긋난다: 실물 {got / pad:.4f}, 규격 {want:.4f}"
        )


def test_v3_geometry_matches_the_printed_artwork() -> None:
    """테두리 두께와 모서리 블록 자리가 실물과 맞는지. 세로 중앙선을 훑어 잰다."""
    img, origin, pad = v3_frame(V3_SAMPLES["magenta"])
    column = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[:, origin + pad // 2]
    ink = column[origin : origin + pad] < 128

    border = runs(ink)[0]
    assert border[0] == 0
    assert abs(border[1] / pad - spec.V3.border_thickness) < TOL_PX / pad


# ---------------------------------------------------------------------------
# chroma_v2 — 유채색 도안 개정판
#
# v3 와 같은 방식으로 실물 PNG 를 다시 스캔한다. 규격과 도안이 어긋난 채로
# 굴러가던 것이 유채색 판독을 통째로 실패시킨 적이 있어, 개정판도 같은 그물을
# 씌운다.
# ---------------------------------------------------------------------------

CHROMA_V2_SAMPLE = ASSETS / "pad_chroma_v2" / "pad_1092_magenta_v2.png"
"""선군 없이 렌더한 개정 도안(``make_pad_chroma_v2.py --no-probe``).

``assets/pad_dual_tones/`` 에 있는 같은 이름의 파일은 선군이 들어간 초판이다.
규격에서 선군을 뺀 것은 아래 변의 띠 검증 여유를 확보하기 위해서이므로,
대조 대상도 선군 없는 쪽이어야 한다.
"""


def test_chroma_v2_anchor_rects_hit_the_right_shade() -> None:
    """``anchor_white`` 자리가 밝고 ``anchor_black`` 자리가 어두운지."""
    for rect in spec.CHROMA_V2.anchor_white:
        assert v3_patch(CHROMA_V2_SAMPLE, rect).mean() > 200, f"흰 앵커가 밝지 않다: {rect}"
    for rect in spec.CHROMA_V2.anchor_black:
        assert v3_patch(CHROMA_V2_SAMPLE, rect).mean() < 55, f"검은 앵커가 어둡지 않다: {rect}"


def test_chroma_v2_margin_is_square_and_matches_the_artwork() -> None:
    """측정면이 규격과 맞고, **정사각형**인지.

    정사각형이라야 사진에서 패드가 90도 돌아가 있어도(EXIF 회전을 imread 가
    반영하지 않아 흔하다) 역산이 무너지지 않는다. 앞 도안은 1.40:1 이라
    정사각형이어야 할 역산 외곽이 5.3:1 로 나온 사례가 있었다.
    """
    img, origin, pad = v3_frame(CHROMA_V2_SAMPLE)
    rect = spec.CHROMA_V2.margin_raw

    field = img[origin : origin + pad, origin : origin + pad].astype(np.int16)
    chroma = (field.max(axis=2) - field.min(axis=2)) > 40

    middle = pad // 2
    top, bottom = runs(chroma[:, middle])[0]
    left, right = runs(chroma[middle, :])[0]

    for label, got, want in (
        ("위", top, rect.y0), ("아래", bottom, rect.y1),
        ("왼쪽", left, rect.x0), ("오른쪽", right, rect.x1),
    ):
        assert abs(got - want * pad) <= TOL_PX, (
            f"측정면 {label} 경계가 규격과 어긋난다: 실물 {got / pad:.4f}, 규격 {want:.4f}"
        )

    assert abs((right - left) - (bottom - top)) <= TOL_PX, (
        f"측정면이 정사각형이 아니다: {(right - left) / pad:.4f} x {(bottom - top) / pad:.4f}"
    )


def test_chroma_v2_leaves_white_gaps_beside_the_measurement_area() -> None:
    """측정면 좌우에 흰 여백이 있는지. **네 변 띠 검증이 여기에 달려 있다.**

    앞 도안은 패드 중간 높이에서 테두리 다음이 곧장 측정면이었다. 어둡게 찍혀
    유채색 명도가 잉크까지 내려가면 둘이 한 덩어리가 되어 띠가 끝나는 자리를
    못 찾고, 좌우 두 변의 검증이 아예 성립하지 않았다.
    """
    img, origin, pad = v3_frame(CHROMA_V2_SAMPLE)
    gap = spec.CHROMA_V2.margin_raw.x0 - spec.CHROMA_V2.border_thickness
    assert gap > spec.CHROMA_V2.border_thickness, (
        f"좌우 흰 여백 {gap:.4f} 이 테두리 두께보다 좁다"
    )

    row = img[int(origin + 0.5 * pad), origin : origin + pad]
    band = row[
        int((spec.CHROMA_V2.border_thickness + 0.01) * pad) : int(
            (spec.CHROMA_V2.margin_raw.x0 - 0.01) * pad
        )
    ]
    assert band.mean() > 200, "측정면 왼쪽이 흰 바탕이 아니다"


def test_chroma_v2_has_no_line_group() -> None:
    """선군을 뺐는지. 아래 변 검증의 여유를 확보하려고 없앤 것이다.

    측정면을 키우느라 아래로 밀린 선군이 테두리와 0.0090 까지 붙어 있었다.
    실물 사진에서 그 틈이 흐림으로 메워지면 테두리와 선군이 한 덩어리가 되어
    아래 변의 띠 두께가 규격의 1.7배로 잡힌다.
    """
    assert spec.CHROMA_V2.line_bars == ()
    assert spec.CHROMA_V2.line_rects == ()
    assert spec.CHROMA_V2.line_gap_rects() == ()

    img, origin, pad = v3_frame(CHROMA_V2_SAMPLE)
    column = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)[:, origin + pad // 2]
    inside = column[origin : origin + pad]

    # 측정면 아래끝부터 테두리 안쪽까지가 전부 흰 바탕이어야 한다.
    below = inside[
        int((spec.CHROMA_V2.margin_raw.y1 + 0.01) * pad) : int(
            (1.0 - spec.CHROMA_V2.border_thickness - 0.005) * pad
        )
    ]
    assert below.min() > 200, f"측정면 아래에 인쇄물이 남아 있다 (최저 {below.min()})"

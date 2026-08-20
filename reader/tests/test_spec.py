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

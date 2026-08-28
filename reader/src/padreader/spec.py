"""패드 정규 규격.

모든 좌표는 **패드 외곽 기준 정규화 좌표** [0, 1] 이다. 원점은 굵은 테두리
바깥 경계의 좌상단이고, 회전이 이미 보정된 정면 좌표계를 가정한다.

이 파일이 규격의 단일 진실공급원이다. ``tools/generate_pad.py`` 가 여기서
도안을 렌더하고 판독 파이프라인이 여기서 ROI 를 얻는다. 규격 숫자를 다른
파일에 쓰지 않는다.

좌표 근거
---------
``assets/`` 의 샘플 PNG(1200x1200) 를 픽셀 스캔해 얻었다. 캔버스 안에서
패드 외곽은 40..1160 이므로 정규화는 ``(canvas_px - 40) / 1120`` 이다.
샘플 렌더의 안티에일리어싱 때문에 실측치는 좌우가 1px 정도 어긋나 있어,
여기서는 대칭이 되도록 정리했다. ``tests/test_spec.py`` 가 샘플 PNG 를 다시
스캔해 이 상수들과 ±3px 안에서 일치하는지 확인한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal

# 샘플 PNG 의 캔버스 규격. 정규화 좌표를 캔버스 픽셀로 되돌릴 때만 쓴다.
SAMPLE_CANVAS = 1200
SAMPLE_PAD_ORIGIN = 40
SAMPLE_PAD_SIZE = 1120

PadTone = Literal["white", "black"]
"""패드 톤. ``white`` = 백색 바탕/흑색 인쇄(흑색 분진용),
``black`` = 흑색 바탕/백색 인쇄(백색 분진용)."""


def from_canvas(px: float) -> float:
    """샘플 캔버스 좌표를 패드 정규화 좌표로."""
    return (px - SAMPLE_PAD_ORIGIN) / SAMPLE_PAD_SIZE


def canvas_length(px: float) -> float:
    """샘플 캔버스 길이를 패드 정규화 길이로."""
    return px / SAMPLE_PAD_SIZE


@dataclass(frozen=True)
class Rect:
    """정규화 좌표계의 축정렬 사각형. 반열린 구간 [x0, x1) x [y0, y1)."""

    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.height

    def inset(self, amount: float) -> "Rect":
        """네 변을 안쪽으로 ``amount`` 만큼 좁힌 사각형."""
        return Rect(self.x0 + amount, self.y0 + amount, self.x1 - amount, self.y1 - amount)

    def to_pixels(self, pad_size_px: int) -> tuple[int, int, int, int]:
        """정면 보정 이미지(한 변 ``pad_size_px``)의 정수 픽셀 슬라이스로.

        반환은 ``(x0, y0, x1, y1)`` 이며 슬라이스에 그대로 쓸 수 있다.
        경계에서 최소 1px 은 남도록 보정한다.
        """
        x0 = int(round(self.x0 * pad_size_px))
        y0 = int(round(self.y0 * pad_size_px))
        x1 = int(round(self.x1 * pad_size_px))
        y1 = int(round(self.y1 * pad_size_px))
        return x0, y0, max(x1, x0 + 1), max(y1, y0 + 1)


@dataclass(frozen=True)
class LineBar:
    """선군의 한 단계. ``y0`` 는 선의 위쪽 경계, ``thickness`` 는 굵기."""

    y0: float
    thickness: float

    @property
    def y1(self) -> float:
        return self.y0 + self.thickness

    def rect(self, x0: float, x1: float) -> Rect:
        return Rect(x0, self.y0, x1, self.y1)


# --------------------------------------------------------------------------
# 규격 본체
# --------------------------------------------------------------------------

# 굵은 외곽 테두리 두께 (실측 66px)
BORDER_THICKNESS = canvas_length(66)

# 모서리 블록: 네 모서리 중 세 곳(TL, TR, BL)에만 있다. 비어 있는 BR 이
# 회전 판정 기준이다.
CORNER_BLOCK_SIZE = canvas_length(73)
CORNER_BLOCK_OFFSET = canvas_length(88)  # 패드 외곽에서 블록까지

# POINT_ID 숫자가 놓이는 영역. 실측 x 431..775, y 112..211 을 감싸도록
# 여유를 둔 박스다. 판독 ROI 로 그대로 쓴다.
#
# 세로로 갇혀 있다. 위로는 테두리 안쪽 경계(y=106)가, 아래로는 측정 여백의
# 시작(y=212)이 막는다. 숫자 자체는 y 112..211 이므로 [109, 212) 이 넣을 수
# 있는 최대다. 아래로 넘기면 글리프가 여백에 새어 들어가 구획 값을 오염시킨다
# (``tests/test_spec.py::test_print_elements_do_not_enter_margin`` 가 막는다).
POINT_ID_BOX = Rect(
    x0=from_canvas(415),
    y0=from_canvas(109),
    x1=from_canvas(791),
    y1=from_canvas(212),
)

# 선군: 굵기 4단계. 실측 x 330..1064.
LINE_GROUP_X0 = from_canvas(330)
LINE_GROUP_X1 = from_canvas(1065)

# v2 의 선군 오른쪽 끝. legacy 의 1065 는 BR 모서리 블록 자리(x 999..1072)를
# 관통해 그 자리를 54% 채운다. BR 은 "비어 있어야 하는 모서리"이자 회전
# 판정의 기준이므로, 선군이 거기까지 뻗으면 판정 마진이 절반으로 깎인다.
# v2 에서는 블록 자리 앞에서 끊는다.
LINE_GROUP_X1_V2 = from_canvas(960)
LINE_BARS: tuple[LineBar, ...] = (
    LineBar(y0=from_canvas(940), thickness=canvas_length(4)),
    LineBar(y0=from_canvas(965), thickness=canvas_length(8)),
    LineBar(y0=from_canvas(994), thickness=canvas_length(16)),
    LineBar(y0=from_canvas(1031), thickness=canvas_length(32)),
)

# 측정 여백. 인쇄물이 상단 밴드(모서리 블록 TL/TR, POINT_ID)와 하단
# 밴드(선군, 모서리 블록 BL)에만 있으므로, 그 사이의 중간 밴드 전체가
# 인쇄물 없는 영역이다. 여기를 격자로 나누면 마스킹이 필요 없고 모든
# 구획의 유효 면적이 같아진다.
#
# 캔버스 기준 인쇄물 하한은 y=211(POINT_ID), 상한은 y=940(선군 1단)이므로
# 비어 있는 구간은 y 212..939 이다. 아래 값은 그 구간을 그대로 쓴 것이며
# 실제 사용 시 ``MARGIN_INSET`` 만큼 더 좁힌다.
MARGIN_RAW = Rect(
    x0=BORDER_THICKNESS,
    y0=from_canvas(212),
    x1=1.0 - BORDER_THICKNESS,
    y1=from_canvas(940),
)

# 여백 경계에서 물러날 기본 여유. 사영변환 잔차와 인쇄 번짐을 흡수한다.
MARGIN_INSET = canvas_length(9)

# 조도 기준으로 쓰는 테두리 링. 바깥/안쪽 모두에서 조금씩 물러나
# 에지 화소를 피한다.
BORDER_RING_INSET = canvas_length(10)

# 2톤 앵커 패치 (v2 도안 전용).
#
# 2점 캘리브레이션 ``(I - I_black) / (I_white - I_black)`` 을 하려면 패드마다
# 흑/백 앵커가 모두 있어야 한다. 테두리 하나만 쓰면 센서 블랙레벨 오프셋이
# 소거되지 않고, 하필 분모인 저반사면에서 오프셋 비중이 가장 크다.
#
# 상단 밴드의 빈 공간(모서리 블록과 POINT_ID 사이)에 좌우 대칭으로 두 쌍을
# 놓는다. 대칭 배치라 좌우 방향 조명 기울기가 쌍 평균에서 상쇄된다.
ANCHOR_PATCH_SIZE = canvas_length(66)
_ANCHOR_Y0 = from_canvas(115)
_A = ANCHOR_PATCH_SIZE


def _anchor(x_canvas: float) -> Rect:
    x0 = from_canvas(x_canvas)
    return Rect(x0, _ANCHOR_Y0, x0 + _A, _ANCHOR_Y0 + _A)


# 좌우 거울 대칭이 되도록 배치한다. 캔버스 중심이 600 이므로 x 와 1200-x-크기가
# 짝이다. 왼쪽 쌍은 (백 225, 흑 305), 오른쪽 쌍은 그 거울인 (흑 829, 백 909).
ANCHOR_WHITE_RECTS: tuple[Rect, ...] = (_anchor(225), _anchor(909))
ANCHOR_BLACK_RECTS: tuple[Rect, ...] = (_anchor(305), _anchor(829))


@dataclass(frozen=True)
class PadSpec:
    """한 벌의 패드 규격.

    ``legacy`` 는 ``assets/`` 의 샘플 도안 그대로이고, ``v2`` 는 여기에 2톤
    앵커 패치를 더한 것이다. 판독 파이프라인은 두 규격 모두에서 동작하며,
    앵커가 없으면 조도 정규화가 테두리 나눗셈으로 자동 강등된다.
    """

    name: str
    border_thickness: float = BORDER_THICKNESS
    corner_block_size: float = CORNER_BLOCK_SIZE
    corner_block_offset: float = CORNER_BLOCK_OFFSET
    point_id_box: Rect = POINT_ID_BOX
    line_group_x0: float = LINE_GROUP_X0
    line_group_x1: float = LINE_GROUP_X1
    line_bars: tuple[LineBar, ...] = LINE_BARS
    margin_raw: Rect = MARGIN_RAW
    margin_inset: float = MARGIN_INSET
    border_ring_inset: float = BORDER_RING_INSET
    anchor_white: tuple[Rect, ...] = ()
    anchor_black: tuple[Rect, ...] = ()
    anchors_protected: bool = False
    """앵커가 분진으로부터 물리적으로 보호되어 있는지 (라미네이트·투명창 등).

    보호되지 않은 앵커로는 2점 캘리브레이션을 할 수 없다. 분진 색은 설계상
    잉크 색과 같으므로(흑색 분진 포인트에 흑색 인쇄 패드), 바탕톤 앵커는
    측정 여백과 완전히 같은 톤이다. 여백이 오염되면 그 앵커도 똑같이
    오염되어 나눗셈이 신호를 그대로 상쇄한다.

    노출된 표면에 분진 면역 기준면은 존재하지 않는다. 드리프트 폭이
    ``(rho_dust - rho_patch) * coverage`` 라서, 드리프트가 0 인 패치는
    반사율이 분진과 같은 것 — 즉 잉크뿐이고, 잉크는 이미 테두리가 준다.
    """

    # ---- 파생 기하 ----

    @property
    def has_anchors(self) -> bool:
        """2점 캘리브레이션이 가능한 규격인지."""
        return bool(self.anchor_white and self.anchor_black)

    @property
    def inner(self) -> Rect:
        """테두리 안쪽 영역 전체."""
        t = self.border_thickness
        return Rect(t, t, 1.0 - t, 1.0 - t)

    @property
    def margin(self) -> Rect:
        """실제 측정에 쓰는 여백. 인쇄물이 전혀 들어가지 않는다."""
        return self.margin_raw.inset(self.margin_inset)

    @property
    def corner_blocks(self) -> dict[str, Rect]:
        """네 모서리의 블록 자리. BR 은 실제로 비어 있지만 회전 판정을 위해
        네 자리를 모두 반환한다 — 어느 자리가 바탕색인지를 보는 것이 판정이다.
        """
        o, s = self.corner_block_offset, self.corner_block_size
        far = 1.0 - o - s
        return {
            "tl": Rect(o, o, o + s, o + s),
            "tr": Rect(far, o, far + s, o + s),
            "bl": Rect(o, far, o + s, far + s),
            "br": Rect(far, far, far + s, far + s),
        }

    @property
    def empty_corner(self) -> str:
        """규격상 비어 있는 모서리. 회전 0도일 때의 기준."""
        return "br"

    def print_element_rects(self) -> dict[str, Rect]:
        """인쇄 요소 전체의 자리. 이름 → 사각형.

        비어 있는 모서리는 인쇄되지 않으므로 뺀다. 앵커는 규격에 있을 때만
        들어간다.
        """
        out = {
            name: rect
            for name, rect in self.corner_blocks.items()
            if name != self.empty_corner
        }
        out["point_id"] = self.point_id_box
        for i, bar in enumerate(self.line_bars):
            out[f"line_{i}"] = bar.rect(self.line_group_x0, self.line_group_x1)
        for i, rect in enumerate(self.anchor_white):
            out[f"anchor_white_{i}"] = rect
        for i, rect in enumerate(self.anchor_black):
            out[f"anchor_black_{i}"] = rect
        return out

    @property
    def line_group_clears_corner_slots(self) -> bool:
        """선군이 모서리 블록 자리를 침범하지 않는지.

        침범하면 비어 있어야 할 BR 자리가 선군으로 채워져 회전 판정
        마진이 깎인다. legacy 도안이 이 상태이며 v2 에서 고쳤다.
        """
        br = self.corner_blocks["br"]
        overlaps_x = self.line_group_x1 > br.x0 and self.line_group_x0 < br.x1
        if not overlaps_x:
            return True
        return all(bar.y1 <= br.y0 or bar.y0 >= br.y1 for bar in self.line_bars)

    @property
    def line_rects(self) -> tuple[Rect, ...]:
        """선군 각 단계의 사각형. 굵은 순이 아니라 얇은 순(위에서 아래)."""
        return tuple(b.rect(self.line_group_x0, self.line_group_x1) for b in self.line_bars)

    def line_gap_rects(self) -> tuple[Rect, ...]:
        """선군 각 단계 **바로 위**의 여백 띠. 선군 대비를 잴 때 기준이 되는 '인접 여백' 이다.

        선 사이 간격의 가운데 절반만 쓴다. 인접 선의 번짐을 피하기 위함이다.

        1단 선 위쪽은 측정 여백과 맞닿아 간격이라 부를 것이 없으므로, 나머지
        단계들의 간격 중앙값을 그대로 빌려 같은 폭의 띠를 잡는다. 단계마다
        여백 띠의 면적이 달라지면 대비값끼리 비교가 안 되기 때문이다.
        """
        gaps = [
            self.line_bars[i].y0 - self.line_bars[i - 1].y1
            for i in range(1, len(self.line_bars))
        ]
        typical = sorted(gaps)[len(gaps) // 2] if gaps else self.margin_inset

        out: list[Rect] = []
        for i, bar in enumerate(self.line_bars):
            prev_end = self.line_bars[i - 1].y1 if i else bar.y0 - typical
            gap = bar.y0 - prev_end
            quarter = gap * 0.25
            out.append(
                Rect(self.line_group_x0, prev_end + quarter, self.line_group_x1, bar.y0 - quarter)
            )
        return tuple(out)

    def border_ring_rects(self) -> tuple[Rect, Rect, Rect, Rect]:
        """테두리 링을 네 변으로 쪼갠 사각형 (상, 하, 좌, 우).

        조명 평면 적합에서 변별로 표본을 뽑을 때 쓴다. 모서리는 두 변이
        겹치므로 상/하 변에서만 잡고 좌/우 변은 그만큼 짧게 잡는다.
        """
        i = self.border_ring_inset
        t = self.border_thickness
        top = Rect(i, i, 1.0 - i, t - i)
        bottom = Rect(i, 1.0 - t + i, 1.0 - i, 1.0 - i)
        left = Rect(i, t + i, t - i, 1.0 - t - i)
        right = Rect(1.0 - t + i, t + i, 1.0 - i, 1.0 - t - i)
        return top, bottom, left, right


LEGACY = PadSpec(name="legacy")
"""``assets/`` 의 샘플 도안 규격. 앵커 패치가 없다."""

V2 = replace(
    LEGACY,
    name="v2",
    line_group_x1=LINE_GROUP_X1_V2,
    anchor_white=ANCHOR_WHITE_RECTS,
    anchor_black=ANCHOR_BLACK_RECTS,
)
"""권장 규격. legacy 에서 두 가지를 고쳤다.

1. 선군을 BR 모서리 블록 자리 앞에서 끊음 — legacy 는 선군이 그 자리를
   54% 채워 회전 판정 마진을 절반으로 깎는다
2. 2톤 앵커 패치 자리 확보

앵커는 자리만 잡아 둔 것이고 ``anchors_protected`` 는 꺼져 있다. 노출된
앵커로 2점 캘리브레이션을 하면 신호가 상쇄되므로, 이 규격에서는 조도
정규화가 테두리 단일 기준으로 동작한다. 물리적으로 앵커를 덮은 패드를
만들면 ``V2_PROTECTED`` 를 쓴다.
"""

V2_PROTECTED = replace(V2, name="v2_protected", anchors_protected=True)
"""앵커를 라미네이트 등으로 덮어 분진이 앉지 않게 만든 패드용.

이 조건에서만 2점 캘리브레이션이 성립한다. 앵커가 실제로 보호되어 있지
않은데 이 규격을 쓰면 분진 신호가 조용히 사라지므로, 도안 제작 사양과
반드시 맞춰야 한다.
"""

# --------------------------------------------------------------------------
# v3 — 실제로 인쇄해 현장에 붙인 도안
# --------------------------------------------------------------------------
#
# 위의 legacy/v2 는 이 저장소의 생성기(``padtools/generate_pad.py``)가 그리는
# 도안이다. 현장에 붙은 패드는 그것이 아니라 ``assets/make_pad_dual_tones.py``
# 와 그 유채색 변종 ``assets/make_pad_chroma.py`` 가 그린 것이고, 두 계보의
# 좌표가 서로 다르다. 판독기가 v2 좌표로 실물을 재고 있었다.
#
# 실물 도안 세 장(백/흑/마젠타)을 픽셀 스캔해 확인한 사실:
#
# - 기하는 세 장이 완전히 동일하다. 다른 것은 측정면 색뿐이다.
# - 앵커는 **바깥이 인쇄색, 안쪽이 바탕색**이다. v2 는 정반대로(바깥이 백,
#   안쪽이 흑) 알고 있어, 유채색 정규화의 분모 ``흰앵커 - 검은앵커`` 가
#   음수가 되어 판독이 전부 실패했다.
# - 측정면은 y 0.1750..0.8036 이다. v2 의 margin_raw 는 y0 이 0.1536 이라
#   위쪽 2% 가 측정면 밖 흰 바탕을 문다.
#
# 아래 값은 ``make_pad_chroma.py`` 의 상수를 그대로 옮긴 것이고,
# ``tests/test_spec.py`` 가 실제 PNG 를 다시 스캔해 어긋나면 잡는다.

V3_BORDER = 0.0589
V3_BLOCK = 0.0643
V3_BLOCK_OFFSET = 0.0786
V3_POINT_ID_BOX = Rect(0.3491, 0.0643, 0.6563, 0.1527)
V3_MARGIN_RAW = Rect(0.0589, 0.1750, 0.9411, 0.8036)
V3_LINE_X0, V3_LINE_X1 = 0.2589, 0.8400

_V3_LINE_Y0 = 0.8036
_V3_LINE_GAP = 0.0196
_V3_LINE_WIDTHS = (0.0027, 0.0063, 0.0134, 0.0286)


def _v3_line_bars() -> tuple[LineBar, ...]:
    """선군 4단. 첫 단이 측정면 바로 아래에서 시작해 간격을 두고 이어진다."""
    bars: list[LineBar] = []
    y = _V3_LINE_Y0
    for width in _V3_LINE_WIDTHS:
        bars.append(LineBar(y0=y, thickness=width))
        y += width + _V3_LINE_GAP
    return tuple(bars)


_V3_ANCHOR = 0.0600
_V3_ANCHOR_Y = 0.0786


def _v3_anchor(x0: float) -> Rect:
    return Rect(x0, _V3_ANCHOR_Y, x0 + _V3_ANCHOR, _V3_ANCHOR_Y + _V3_ANCHOR)


V3_ANCHOR_INK: tuple[Rect, ...] = (_v3_anchor(0.1731), _v3_anchor(0.7723))
"""인쇄색으로 찍힌 앵커. 좌우 쌍의 **바깥쪽**이다."""

V3_ANCHOR_BASE: tuple[Rect, ...] = (_v3_anchor(0.2451), _v3_anchor(0.7003))
"""바탕색으로 남겨 둔 앵커. 좌우 쌍의 **안쪽**이다."""

_V3 = PadSpec(
    name="_v3",
    border_thickness=V3_BORDER,
    corner_block_size=V3_BLOCK,
    corner_block_offset=V3_BLOCK_OFFSET,
    point_id_box=V3_POINT_ID_BOX,
    line_group_x0=V3_LINE_X0,
    line_group_x1=V3_LINE_X1,
    line_bars=_v3_line_bars(),
    margin_raw=V3_MARGIN_RAW,
    anchors_protected=True,
)

V3 = replace(
    _V3,
    name="v3",
    anchor_white=V3_ANCHOR_BASE,
    anchor_black=V3_ANCHOR_INK,
)
"""백색 바탕 실물 도안. **유채색(마젠타) 패드도 이것을 쓴다.**

``anchor_white``/``anchor_black`` 은 자리의 역할이 아니라 **거기가 실제로
밝은가 어두운가**를 뜻한다(``render.py`` 가 각각 255, 0 으로 그린다). 백색
바탕 패드는 인쇄색이 검정이므로 바깥(인쇄색)이 검은 앵커, 안쪽(바탕색)이
흰 앵커다.

마젠타 패드는 측정면만 유채색이고 앵커가 놓인 위쪽 밴드는 백색 바탕에 검은
인쇄라, 앵커 관점에서는 백색 패드와 완전히 같다.
"""

V3_BLACK = replace(
    _V3,
    name="v3_black",
    anchor_white=V3_ANCHOR_INK,
    anchor_black=V3_ANCHOR_BASE,
)
"""흑색 바탕 실물 도안. 기하는 ``V3`` 와 같고 앵커의 명암만 뒤집힌다.

흑색 바탕은 인쇄색이 흰색이므로 바깥(인쇄색)이 흰 앵커, 안쪽(바탕색)이
검은 앵커다. 같은 자리를 가리키면서 이름만 맞바꾼 것이며, 이 구분을 두지
않으면 흑색 패드에서 정규화 분모의 부호가 뒤집힌다.
"""

# --------------------------------------------------------------------------
# chroma_v3 — 유채색 도안 개정판 (assets/make_pad_chroma_v3.py)
# --------------------------------------------------------------------------
#
# ``V3`` 는 그대로 둔다. 현장에 붙어 있는 패드와 이미 찍어 둔 기준 사진이 그
# 도안이라, 덮어쓰면 지난 판독을 다시 읽을 수 없다. 실물을 교체하면
# ``chroma.spec`` 을 이 규격으로 바꾼다.
#
# 무엇이 달라졌나 - 실물 PNG 를 픽셀 스캔해 확인한 값이다.
#
# 1. **측정면이 정사각형이 되었다** (0.6822 x 0.6831, 실측). 앞 도안은
#    1.40:1 이라, 사진에서 패드가 90도 돌아가 있으면(EXIF 회전을 imread 가
#    반영하지 않아 흔하다) 가로세로가 뒤바뀌어 역산이 무너졌다 - 정사각형
#    이어야 할 외곽이 5.3:1 로 나온 사례가 있었다.
# 2. **측정면 좌우에 흰 여백이 생겼다** (0.1000, 테두리의 1.70배). 앞 도안은
#    패드 중간 높이에서 테두리 다음이 곧장 측정면이라, 어둡게 찍히면 잉크와
#    측정면이 한 덩어리가 되어 좌우 두 변의 띠 검증이 아예 성립하지 않았다.
#    이제 네 변 모두 잰다.
# 3. **선군을 뺐다.** 측정면을 키우느라 아래로 밀린 선군이 테두리와 0.0090
#    까지 붙어, 실물 사진에서 흐려지면 테두리와 한 덩어리가 되어 아래 변
#    검증이 어긋날 참이었다. 좌우를 살리고 아래를 잃을 이유가 없다.
# 4. **앵커가 커졌다** (0.0600 -> 0.0680). 정합이 조금 밀려도 측정 창이 패치
#    밖으로 미끄러지지 않는다.
#
# 흑백 순서는 그대로다 - 바깥이 인쇄색(검정), 안쪽이 바탕색(흰색).

CHROMA_V3_MARGIN_RAW = Rect(0.1550, 0.1700, 0.8450, 0.8600)
"""측정면. 한 변 0.6900 정사각이며 가로로는 패드 중앙이다.

선군을 걷어내 아래로 여유가 생겼지만 한 변이 그만큼 늘지는 않았다. 측정면이
모서리 블록과 같은 높이까지 내려오므로 이제는 세로가 아니라 **좌우 모서리 블록
사이 간격**(0.1429~0.8571)이 한 변을 묶는다. 정사각형이라는 제약 때문에 세로
여유가 남아도 쓸 수 없다.

세로로는 중앙이 아니다(중심 y 0.5150 - 위 여백 0.1111, 아래 0.0811). 그래서
정사각형만으로 90도 모호성이 완전히 사라지지는 않는다 - 대응이 한 칸 틀리면
역산 외곽이 밀린다. 그 몫은 도안이 아니라 검출 쪽에서 없앤다:
``chroma._best_pad_corners`` 가 네 대응을 모두 시험해 90도는 테두리 띠로,
180도는 모서리 블록으로 가른다.
"""

_CHROMA_V3_ANCHOR = 0.0680
_CHROMA_V3_ANCHOR_Y = 0.0786


def _chroma_v3_anchor(x0: float) -> Rect:
    a = _CHROMA_V3_ANCHOR
    return Rect(x0, _CHROMA_V3_ANCHOR_Y, x0 + a, _CHROMA_V3_ANCHOR_Y + a)


CHROMA_V3_ANCHOR_INK: tuple[Rect, ...] = (
    _chroma_v3_anchor(0.1669),
    _chroma_v3_anchor(0.7651),
)
"""인쇄색(검정)으로 찍힌 앵커. 좌우 쌍의 바깥쪽이다."""

CHROMA_V3_ANCHOR_BASE: tuple[Rect, ...] = (
    _chroma_v3_anchor(0.2469),
    _chroma_v3_anchor(0.6851),
)
"""바탕색(흰색)으로 남겨 둔 앵커. 좌우 쌍의 안쪽이다."""

CHROMA_V3 = PadSpec(
    name="chroma_v3",
    border_thickness=V3_BORDER,
    corner_block_size=V3_BLOCK,
    corner_block_offset=V3_BLOCK_OFFSET,
    point_id_box=V3_POINT_ID_BOX,
    line_group_x0=V3_LINE_X0,
    line_group_x1=V3_LINE_X1,
    # 선군을 인쇄하지 않는다. 위 x 범위는 남겨 두지만 단이 없으므로 아무 자리도
    # 차지하지 않는다 - line_rects()/line_gap_rects() 가 빈 목록을 낸다.
    line_bars=(),
    margin_raw=CHROMA_V3_MARGIN_RAW,
    anchor_white=CHROMA_V3_ANCHOR_BASE,
    anchor_black=CHROMA_V3_ANCHOR_INK,
    anchors_protected=True,
)
"""백색 바탕에 유채색 정사각 측정면. 현행 유채색 도안의 개정판이다.

``assets/make_pad_chroma_v3.py`` 가 그리는 도안이다. 중간판(v2)은 선군을 남긴
채 한 변이 0.6820 이었고, 이 판에서 선군을 걷어내며 0.6900 으로 키웠다.
"""

SPECS: dict[str, PadSpec] = {
    LEGACY.name: LEGACY,
    V2.name: V2,
    V2_PROTECTED.name: V2_PROTECTED,
    V3.name: V3,
    V3_BLACK.name: V3_BLACK,
    CHROMA_V3.name: CHROMA_V3,
}


def get_spec(name: str) -> PadSpec:
    try:
        return SPECS[name]
    except KeyError:
        raise ValueError(f"알 수 없는 패드 규격: {name!r} (가능: {sorted(SPECS)})") from None

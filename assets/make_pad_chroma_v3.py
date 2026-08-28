"""참조 패드 도안 시안 v2 — 정사각 유채색 측정면.

``make_pad_chroma.py`` 에서 측정면의 **형태와 위치**를 고치고 선군을 걷어낸
것이다. 검은 테두리 두께, 모서리 블록 셋(BR 비움), 앵커의 흑백 순서,
POINT_ID 상자는 그대로다.

판독 실증에서 나온 세 가지를 도안 단계에서 없앤다.

1. **측정면이 좌우 테두리에 붙어 있어 검증이 반쪽만 돌던 문제.**

   판독기는 검출한 사각형이 진짜 패드인지 네 변의 잉크 띠 두께로 확인한다.
   앞 도안은 패드 중간 높이에서 테두리 다음이 곧장 측정면이라 좌우에 밝은
   구간이 없었다. 어둡게 찍혀 마젠타 명도가 13~33까지 떨어지면 잉크와
   구분되지 않아 띠가 끝나는 자리를 못 찾고, 위·아래 두 변만 검증됐다.

   측정면 좌우에 흰 여백을 둔다. 폭은 테두리 두께의 1.7배로, 어둡게 찍혀도
   테두리와 측정면이 확실히 끊긴다.

2. **측정면이 정사각형이 아니라 90도 모호성이 있던 문제. 가장 심각했다.**

   판독기는 유채색 덩어리를 먼저 찾고 거기서 패드 외곽을 역산한다. 카메라가
   EXIF 회전을 기록하면 원본 픽셀 배열에서 패드가 90도 돌아가 있는 경우가
   흔한데, 측정면이 1.40:1 이면 가로세로가 뒤바뀌어 좌표계가 무너진다.
   실측에서 정사각형이어야 할 역산 외곽이 5.3:1 로 나온 사례가 있었다.

   측정면을 정사각형으로 만든다. 90도 틀려도 결과가 같으므로 이 문제 자체가
   사라진다.

3. **측정면이 작아 역산 오차가 증폭되던 문제.**

   안쪽 사각형에서 바깥을 밀어내는 구조라 꼭짓점 오차가 배율만큼 커져
   전달된다. 앞 도안은 측정면 세로가 패드 높이의 63% 라 약 1.6배였다.
   정사각형 한 변을 68% 로 키워 배율을 1.47배로 낮춘다.

선군을 뺐다
-----------

하단 선군 4단을 제거했다. 감도 비교용 보조 지표였고 상시 판독에 쓰이지
않는데, 아래쪽 세로 공간을 0.11 넘게 차지하고 있었다. 선명도는
``quality.py`` 가 원본 이미지에서 Tenengrad 와 에지 상승 거리로 직접 재므로
인쇄된 기준선이 없어도 판정된다.

빠진 자리만큼 측정면을 키웠다. 다만 늘어난 폭은 0.682 에서 0.690 으로
크지 않다 — 선군을 빼도 측정면이 아래로 내려가면 BL 모서리 블록과 같은
높이가 되므로, 이제는 세로가 아니라 **좌우 모서리 블록 사이 간격**이 한 변을
묶는다. 정사각형이라는 제약 때문에 세로 여유가 남아도 쓸 수 없다.

무엇을 내주었나
---------------

측정 면적이 패드 면적의 55% 에서 47.6% 로 줄어든다. 분진 신호를 모으는
면적이라 통계적으로는 손해다. 다만 측정 화소가 여전히 수십만 개라 실용상
여유가 있고, 정합이 틀리는 것보다는 면적이 조금 주는 편이 낫다.

앵커 패치는 한 변을 0.0600 에서 0.0680 으로 키웠다. 필수 요청은 아니었으나
공간이 남아 반영한다 — 정합이 조금만 밀려도 측정 창이 패치 밖으로
미끄러지던 여유 부족을 조금 덜어 준다. **흑백 순서는 바꾸지 않았다**:
바깥이 인쇄색(검정), 안쪽이 바탕색(흰색)이다.

    python make_pad_chroma_v2.py --ids 1088 1089 1090 1091 1092
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# 캔버스 — v1 과 동일
# --------------------------------------------------------------------------

PAD = 1120
QUIET = 0.125

ORIGIN = round(PAD * QUIET)
CANVAS = PAD + 2 * ORIGIN


def px(v: float) -> float:
    return ORIGIN + v * PAD


def length(v: float) -> float:
    return v * PAD


# --------------------------------------------------------------------------
# 바탕색 — v1 과 동일
# --------------------------------------------------------------------------

TONES: dict[str, tuple[int, int, int]] = {
    "magenta": (236, 0, 140),
    "yellow": (255, 241, 0),
    "cyan": (0, 174, 239),
}
"""측정면 바탕색 후보. 전부 CMYK 프로세스 원색이라 잉크를 섞지 않고 한 판으로
찍힌다. 배치가 달라져도 색이 흔들릴 여지가 가장 작다.

``yellow`` 를 추가했다. 명도가 218 로 백색 패드(255)에 가까워, 어둡게 찍혀도
잉크와의 대비가 살아남는다 — 마젠타는 명도 87 이라 노출이 조금만 부족해도
잉크와 뭉친다. 채도 감도는 마젠타의 93% 수준이라 잃는 것이 거의 없다.
어느 쪽을 쓸지는 시험 인쇄물을 현장 조명에서 실측해 정한다.
"""

DEFAULT_TONE = "magenta"


# --------------------------------------------------------------------------
# 규격 — 변경 없는 항목
# --------------------------------------------------------------------------

BORDER = 0.0589
"""검은 테두리 두께. 정합 검증의 기준이므로 바꾸지 않는다."""

BLOCK = 0.0643
BLOCK_OFFSET = 0.0786
"""모서리 블록. TL·TR·BL 만 인쇄하고 BR 을 비워 회전 방향을 알린다."""

ID_BOX = (0.3491, 0.0643, 0.6563, 0.1527)
ID_FONT = 132 / 1120

ANCHOR_GAP = 0.0120
ANCHOR_Y = 0.0786
LAMINATE_PAD = 0.0140
ID_CLEARANCE = 0.0300
BLOCK_CLEARANCE = 0.0100


# --------------------------------------------------------------------------
# 규격 — v2 에서 바뀐 항목
# --------------------------------------------------------------------------

ANCHOR = 0.0680
"""앵커 패치 한 변. v1 의 0.0600 에서 키웠다.

2점 캘리브레이션 창이 정합 오차로 패치 밖에 걸치면 흑도 백도 아닌 값을 재게
되는데, 그 경우 span 이 우연히 양수면 실패조차 하지 않고 틀린 값이 나간다.
패치가 클수록 그 여유가 는다.
"""

MEASURE_TOP = 0.1700
"""측정면 위쪽 y.

위로는 앵커 라미네이트 표시선(0.1606)과 POINT_ID 상자 아래(0.1527)를 피해야
한다. 0.1700 은 라미네이트 선에서 0.0094 떨어진 자리다.
"""

MEASURE_SIDE = 0.6900
"""측정면 한 변. 정사각형이다.

선군을 뺀 뒤로는 세로가 아니라 **좌우 모서리 블록 사이 간격**이 한 변을 묶는다.
측정면이 블록과 같은 높이까지 내려오므로 x 로 겹치면 안 되고, 블록 안쪽
가장자리가 0.1429 와 0.8571 이라 간격이 0.7142 다. 여기서 좌우로
``BLOCK_CLEARANCE`` 만큼 물러난 값이 상한이다.

세로로는 여유가 더 있지만(아래 여백 0.0811) 정사각형이라 쓸 수 없다.
"""

MEASURE_X0 = round((1.0 - MEASURE_SIDE) / 2, 4)
"""측정면 왼쪽 x. 가로 중앙에 둔다."""

MARGIN = (MEASURE_X0, MEASURE_TOP,
          round(MEASURE_X0 + MEASURE_SIDE, 4),
          round(MEASURE_TOP + MEASURE_SIDE, 4))
"""측정 여백. 인쇄물이 전혀 없는 정사각 구간이다."""

SIDE_GAP = round(MEASURE_X0 - BORDER, 4)
"""측정면과 테두리 안쪽 사이의 흰 여백 폭. 테두리 두께의 1.7배."""


def corner_blocks() -> dict[str, tuple[float, float, float, float]]:
    near, far = BLOCK_OFFSET, 1.0 - BLOCK_OFFSET - BLOCK
    return {
        "tl": (near, near, near + BLOCK, near + BLOCK),
        "tr": (far, near, far + BLOCK, near + BLOCK),
        "bl": (near, far, near + BLOCK, far + BLOCK),
        "br": (far, far, far + BLOCK, far + BLOCK),
    }


def anchor_pair_x0(side: str) -> float:
    blocks = corner_blocks()
    width = 2 * ANCHOR + ANCHOR_GAP
    if side == "left":
        block_edge, id_edge = blocks["tl"][2], ID_BOX[0]
        x0 = id_edge - ID_CLEARANCE - LAMINATE_PAD - width
        floor = block_edge + BLOCK_CLEARANCE + LAMINATE_PAD
        return max(x0, floor)
    block_edge, id_edge = blocks["tr"][0], ID_BOX[2]
    x0 = id_edge + ID_CLEARANCE + LAMINATE_PAD
    ceiling = block_edge - BLOCK_CLEARANCE - LAMINATE_PAD - width
    return min(x0, ceiling)


def anchor_rects(side: str) -> tuple[tuple, tuple]:
    """(어두운 패치, 밝은 패치) 자리.

    좌우 쌍 모두 **바깥이 어두운 쪽, 안쪽이 밝은 쪽**이다. 판독기가 이 순서를
    규격으로 의존하므로 바꾸지 않는다.
    """
    x0 = anchor_pair_x0(side)
    first = (x0, ANCHOR_Y, x0 + ANCHOR, ANCHOR_Y + ANCHOR)
    x1 = x0 + ANCHOR + ANCHOR_GAP
    second = (x1, ANCHOR_Y, x1 + ANCHOR, ANCHOR_Y + ANCHOR)
    return (first, second) if side == "left" else (second, first)


def laminate_rect(side: str) -> tuple[float, float, float, float]:
    """라미네이트 창 표시선 자리."""
    dark, light = anchor_rects(side)
    return (min(dark[0], light[0]) - LAMINATE_PAD,
            ANCHOR_Y - LAMINATE_PAD,
            max(dark[2], light[2]) + LAMINATE_PAD,
            ANCHOR_Y + ANCHOR + LAMINATE_PAD)


# --------------------------------------------------------------------------
# 렌더
# --------------------------------------------------------------------------

BUNDLED_FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf"

FONT_CANDIDATES = (
    str(BUNDLED_FONT),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw_pad(point_id: str, tone: str, path: Path) -> None:
    white, black = (255, 255, 255), (0, 0, 0)
    field = TONES[tone]
    ink, bg = black, white

    img = Image.new("RGB", (CANVAS, CANVAS), bg)
    d = ImageDraw.Draw(img)

    def rect(box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        d.rectangle([px(x0), px(y0), px(x1), px(y1)],
                    fill=fill, outline=outline, width=width)

    # 1) 측정면 — 정사각 유채색. 좌우로 흰 여백이 남는다.
    rect(MARGIN, fill=field)

    # 2) 외곽 테두리
    d.rectangle(
        [px(0), px(0), px(1.0) - 1, px(1.0) - 1],
        outline=ink, width=round(length(BORDER)),
    )

    # 3) 모서리 블록 셋
    blocks = corner_blocks()
    for name in ("tl", "tr", "bl"):
        rect(blocks[name], fill=ink)

    # 4) 2톤 앵커. 바깥이 검정, 안쪽이 흰색.
    for side in ("left", "right"):
        dark, light = anchor_rects(side)
        rect(dark, fill=ink)
        rect(light, fill=white)
        rect(laminate_rect(side), outline=ink,
             width=max(1, round(length(0.0027))))

    # 5) POINT_ID
    font = load_font(round(length(ID_FONT)))
    d.text(
        (px((ID_BOX[0] + ID_BOX[2]) / 2), px((ID_BOX[1] + ID_BOX[3]) / 2)),
        point_id, font=font, fill=ink, anchor="mm",
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, dpi=(300, 300))


def check_layout() -> list[str]:
    """도안 요소가 서로 침범하지 않는지 확인한다.

    좌표를 손으로 고칠 때 조용히 겹치는 것을 막기 위한 것이다. 앵커 흑백이
    반대로 들어가 있던 사고가 정면 보정 직후 한 번만 확인했으면 즉시 드러났을
    문제였다는 점에서, 도안 쪽에도 같은 확인을 둔다.
    """
    problems: list[str] = []
    blocks = corner_blocks()
    x0, y0, x1, y1 = MARGIN

    if abs((x1 - x0) - (y1 - y0)) > 1e-6:
        problems.append(f"측정면이 정사각형이 아니다: {x1-x0:.4f} x {y1-y0:.4f}")

    if SIDE_GAP < BORDER:
        problems.append(f"좌우 흰 여백 {SIDE_GAP:.4f} 이 테두리 두께 "
                        f"{BORDER} 보다 좁다")

    bottom_gap = (1.0 - BORDER) - y1
    if bottom_gap < BORDER:
        problems.append(f"아래 흰 여백 {bottom_gap:.4f} 이 테두리 두께 "
                        f"{BORDER} 보다 좁다")

    for name, b in blocks.items():
        if not (b[2] <= x0 or b[0] >= x1 or b[3] <= y0 or b[1] >= y1):
            problems.append(f"측정면이 {name} 모서리 블록과 겹친다")

    for side in ("left", "right"):
        lam = laminate_rect(side)
        if lam[3] > y0:
            problems.append(f"{side} 라미네이트 표시선이 측정면을 침범한다 "
                            f"({lam[3]:.4f} > {y0:.4f})")
        for name in ("tl", "tr"):
            b = blocks[name]
            if not (b[2] <= lam[0] or b[0] >= lam[2]):
                problems.append(f"{side} 라미네이트 표시선이 {name} 블록과 겹친다")

    if ID_BOX[3] > y0:
        problems.append("POINT_ID 상자가 측정면을 침범한다")

    left_clear = x0 - blocks["tl"][2]
    right_clear = blocks["tr"][0] - x1
    if min(left_clear, right_clear) < BLOCK_CLEARANCE:
        problems.append(f"측정면과 모서리 블록 사이 간격이 좁다 "
                        f"(좌 {left_clear:.4f}, 우 {right_clear:.4f}, "
                        f"최소 {BLOCK_CLEARANCE})")

    return problems


def print_spec(tone: str) -> None:
    """판독기 규격(spec.py)에 옮겨 적을 값."""
    r, g, b = TONES[tone]
    x0, y0, x1, y1 = MARGIN
    print(f"캔버스 {CANVAS}  패드 {PAD}  원점 {ORIGIN}  바깥 여백 {QUIET}")
    print()
    print(f"  측정면 바탕색      {tone}  RGB({r}, {g}, {b})  #{r:02X}{g:02X}{b:02X}")
    print(f"  검은 테두리        0 – {BORDER}")
    print(f"  측정면(정사각)     ({x0}, {y0}) – ({x1}, {y1})")
    print(f"                     한 변 {MEASURE_SIDE}  "
          f"면적 {MEASURE_SIDE ** 2 * 100:.1f}%")
    print(f"  좌우 흰 여백       {SIDE_GAP}  (테두리 두께의 "
          f"{SIDE_GAP / BORDER:.2f}배)")
    print(f"  아래 흰 여백       {round((1.0 - BORDER) - y1, 4)}  (테두리 두께의 "
          f"{((1.0 - BORDER) - y1) / BORDER:.2f}배)")
    print(f"  역산 증폭 배율     {1 / MEASURE_SIDE:.2f}배  "
          f"(v1 은 {1 / 0.6286:.2f}배)")
    print()
    for side in ("left", "right"):
        dark, light = anchor_rects(side)
        print(f"  앵커 {side:<5} 검정(바깥) "
              f"{tuple(round(v, 4) for v in dark)}")
        print(f"  앵커 {side:<5} 흰색(안쪽) "
              f"{tuple(round(v, 4) for v in light)}")
    print(f"  앵커 한 변         {ANCHOR}  (v1 은 0.0600)")
    print()
    blocks = corner_blocks()
    for name in ("tl", "tr", "bl", "br"):
        mark = "비움" if name == "br" else "인쇄"
        print(f"  모서리 블록 {name:<3} {tuple(round(v, 4) for v in blocks[name])}"
              f"  {mark}")
    print()
    print(f"  POINT_ID 상자      {ID_BOX}")
    print(f"  번호 글자 크기      {round(length(ID_FONT))}px")
    print(f"  선군                제거됨 (v1 에 있던 하단 4단)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="assets/pad_chroma_v2", help="출력 폴더")
    parser.add_argument(
        "--ids", nargs="+",
        default=["1088", "1089", "1090", "1091", "1092"],
        help="관측 포인트 번호.",
    )
    parser.add_argument(
        "--tone", default=DEFAULT_TONE, choices=sorted(TONES),
        help=f"측정면 바탕색 (기본 {DEFAULT_TONE})",
    )
    args = parser.parse_args(argv)

    problems = check_layout()
    if problems:
        print("도안 배치 문제:")
        for p in problems:
            print(f"  - {p}")
        return 1

    out = Path(args.out)
    for tid in args.ids:
        draw_pad(tid, args.tone, out / f"pad_{tid}_{args.tone}_v2.png")
    print_spec(args.tone)
    print(f"\n{len(args.ids)}장 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

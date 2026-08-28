"""참조 패드 도안 시안 — 유채색 측정면.

``make_pad_dual_tones.py`` 의 2톤 앵커 도안을 그대로 두고, **측정 여백만
유채색 단색으로** 바꾼 것이다. 좌표, 테두리, 모서리 블록, 앵커, 번호, 선군은
전부 앞 도안과 같다. 판독기 규격에서 바뀌는 것은 측정면의 바탕색뿐이다.

무엇을 고쳤나
-------------

1. **측정 여백을 유채색으로 채운다.**

   흑·백 두 종류를 만들 필요가 없어진다. 지금은 흑색 분진을 백색 패드로,
   백색 분진을 흑색 패드로 잡느라 한 관측점에 두 장을 붙여야 한다. 유채색
   위에서는 **검은 분진도 흰 분진도 똑같이 채도를 떨어뜨린다.** 분진은
   무채색이고 바탕은 유채색이므로, 어느 쪽이 앉든 바탕색이 회색 쪽으로
   끌려간다. 한 장으로 둘 다 잡힌다.

2. **균일 분진과 조명 변화의 축퇴가 풀린다.**

   백색 패드에서는 패드 전체에 고르게 깔린 분진과 조명이 조금 어두워진 것이
   광학적으로 같다. R, G, B 가 똑같이 내려가므로 구별할 정보 자체가 없다.

   유채색 위에서는 다르다. 조도가 변하면 세 채널이 **같은 비율로** 움직여
   채도가 유지되고, 분진이 앉으면 바탕색 채널은 내려가고 나머지 채널은
   올라가 채도가 떨어진다. 채도는 조도에 불변이다.

   2톤 앵커가 이미 게인과 바닥값을 지우지만, 그건 앵커에 분진이 앉지 않는다는
   전제 위에서만 성립한다. 채도는 그 전제 없이도 성립한다. 두 방식이 서로를
   보완한다.

3. **원색 잉크 한 가지만 쓴다.**

   기본값은 프로세스 마젠타다. CMYK 인쇄에서 잉크를 섞지 않고 한 판으로
   찍히는 색이라, 배치가 달라져도 색이 흔들릴 여지가 가장 작다. 색을 섞어
   만들면 망점 비율에 따라 관측점마다 바탕색이 미묘하게 달라진다.

   현장 바닥이 녹색 계열이므로 녹색은 쓰지 않는다. 마젠타는 공정 설비와
   안전 표지 어디에도 잘 쓰이지 않아 배경과 겹칠 여지가 가장 작다. 대안으로
   시안을 둔다.

   바탕색 자체의 절대값은 규격에 박지 않는다. 관측점마다 부착 직후 기준
   사진을 찍으므로, 인쇄 편차와 조명 조건은 그 기준 사진이 흡수한다.

무엇을 그대로 두었나
--------------------

바깥 흰 여백, 테두리, 모서리 블록 셋, 2톤 앵커와 라미네이트 창 표시, 번호
상자, 선군은 앞 도안과 완전히 같다. 앵커를 흑·백으로 두는 것도 그대로다 —
채널별로 ``(관측값 - 흑색패치) / (백색패치 - 흑색패치)`` 를 계산하면 게인과
바닥값뿐 아니라 카메라 화이트밸런스까지 함께 지워진다. 채도를 재려면 이
채널별 보정이 앞서야 한다.

바깥 여백만 백색으로 고정한다. 앞 도안은 여백을 패드 바탕색과 같게 두었지만,
여기서는 바탕이 유채색이라 여백까지 물들이면 배경 대비가 흔들린다.

    python make_pad_chroma.py --ids 1088 1089 1090 1091 1092
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# 캔버스
# --------------------------------------------------------------------------

PAD = 1120
"""패드 외곽 한 변. 정규화 좌표 1.0 에 해당하는 픽셀 수. 앞 도안과 같다."""

QUIET = 0.125
"""패드 바깥에 두를 흰 여백. 패드 한 변 대비 비율."""

ORIGIN = round(PAD * QUIET)
CANVAS = PAD + 2 * ORIGIN


def px(v: float) -> float:
    """정규화 좌표를 캔버스 픽셀로."""
    return ORIGIN + v * PAD


def length(v: float) -> float:
    return v * PAD


# --------------------------------------------------------------------------
# 바탕색
# --------------------------------------------------------------------------

TONES: dict[str, tuple[int, int, int]] = {
    "magenta": (236, 0, 140),
    "cyan": (0, 174, 239),
    "violet": (146, 39, 143),
}
"""측정면 바탕색 후보.

``magenta`` 와 ``cyan`` 은 CMYK 프로세스 원색이다. 잉크를 섞지 않고 한 판으로
찍히므로 배치 간 색 편차가 가장 작다. ``violet`` 은 두 잉크를 겹친 색이라
재현성이 한 단계 떨어지지만, 시안이 설비 도장색과 겹치는 개소가 있으면
대안이 된다.

녹색 계열은 두지 않는다. 현장 바닥과 겹친다.
"""

DEFAULT_TONE = "magenta"


# --------------------------------------------------------------------------
# 규격 (정규화 좌표) — 앞 도안과 동일
# --------------------------------------------------------------------------

BORDER = 0.0589
"""테두리 두께. 굵을수록 조명 기준값이 안정되고 꼭짓점 적합 표본이 는다."""

BLOCK = 0.0643
BLOCK_OFFSET = 0.0786
"""모서리 블록 크기와 패드 외곽에서의 거리."""

TOP_BAND = (BORDER, 0.1750)
"""위쪽 인쇄 밴드. 모서리 블록, POINT_ID, 앵커가 여기 들어간다."""

ID_BOX = (0.3491, 0.0643, 0.6563, 0.1527)
"""POINT_ID 글자가 들어갈 자리."""

ID_FONT = 132 / 1120
"""번호 글자 크기. 패드 한 변 대비 비율."""

ANCHOR = 0.0600
"""앵커 패치 한 변."""

ANCHOR_GAP = 0.0120
"""흑·백 패치 사이 간격. 붙여 두면 인쇄 번짐으로 서로 물든다."""

ANCHOR_Y = 0.0786
"""앵커 패치 위쪽 y. 모서리 블록과 같은 줄."""

LAMINATE_PAD = 0.0140
"""라미네이트 창 표시선이 앵커 바깥으로 물러날 거리."""

ID_CLEARANCE = 0.0300
"""라미네이트 표시선과 번호 상자 사이에 비워 둘 간격."""

BLOCK_CLEARANCE = 0.0100
"""모서리 블록과 라미네이트 표시선 사이 최소 간격."""

MARGIN = (BORDER, 0.1750, 1.0 - BORDER, 0.8036)
"""측정 여백. 인쇄물이 전혀 없는 구간이다. 패드 면적의 55%.

앞 도안에서는 여기가 바탕색 그대로였다. 이 도안에서는 유채색으로 채운다.
"""

LINE_X = (0.2589, 0.8400)
"""선군 가로 범위. 오른쪽 끝을 0.84 로 당겨 BR 모서리 자리를 비운다."""

LINE_Y0 = 0.8036
LINE_WIDTHS = (0.0027, 0.0063, 0.0134, 0.0286)
LINE_GAP = 0.0196
"""선군 4단. 굵기가 두 배씩 차이 난다."""


def corner_blocks() -> dict[str, tuple[float, float, float, float]]:
    """네 모서리 블록 자리. 도안에는 BR 을 뺀 셋만 찍는다."""
    near, far = BLOCK_OFFSET, 1.0 - BLOCK_OFFSET - BLOCK
    return {
        "tl": (near, near, near + BLOCK, near + BLOCK),
        "tr": (far, near, far + BLOCK, near + BLOCK),
        "bl": (near, far, near + BLOCK, far + BLOCK),
        "br": (far, far, far + BLOCK, far + BLOCK),
    }


def anchor_pair_x0(side: str) -> float:
    """앵커 쌍의 시작 x. 앞 도안과 같은 계산."""
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
    """(어두운 패치, 밝은 패치) 자리. 좌우 쌍의 흑백 순서를 뒤집는다."""
    x0 = anchor_pair_x0(side)
    first = (x0, ANCHOR_Y, x0 + ANCHOR, ANCHOR_Y + ANCHOR)
    x1 = x0 + ANCHOR + ANCHOR_GAP
    second = (x1, ANCHOR_Y, x1 + ANCHOR, ANCHOR_Y + ANCHOR)
    return (first, second) if side == "left" else (second, first)


# --------------------------------------------------------------------------
# 렌더
# --------------------------------------------------------------------------

BUNDLED_FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf"
"""저장소에 넣어 둔 폰트. 인쇄와 판독이 같은 파일을 쓴다."""

FONT_CANDIDATES = (
    str(BUNDLED_FONT),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """굵은 산세리프. 없으면 기본 폰트로 떨어진다."""
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw_pad(point_id: str, tone: str, path: Path, probe: bool = True) -> None:
    """도안 한 장.

    ``tone`` 은 측정면 바탕색 이름이다. 인쇄물(테두리, 블록, 앵커 어두운 쪽,
    번호, 선군)은 전부 흑색이고, 앵커 밝은 쪽과 바깥 여백은 백색이다.
    유채색은 측정 여백에만 들어간다.
    """
    white, black = (255, 255, 255), (0, 0, 0)
    field = TONES[tone]
    ink, bg = black, white

    # 바깥 여백은 백색으로 고정한다. 테두리 잉크가 배경에 직접 닿지 않게
    # 하는 것이 목적이므로 유채색으로 물들일 이유가 없다.
    img = Image.new("RGB", (CANVAS, CANVAS), bg)
    d = ImageDraw.Draw(img)

    def rect(box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        d.rectangle([px(x0), px(y0), px(x1), px(y1)],
                    fill=fill, outline=outline, width=width)

    # 1) 측정 여백 — 유채색. 인쇄 요소보다 먼저 깔아 두면 이후 요소가
    #    그 위에 얹힌다. 선군은 이 구간 아래에 있으므로 겹치지 않는다.
    rect(MARGIN, fill=field)

    # 2) 외곽 테두리 — 정합 기준점이자 조명 기준면.
    d.rectangle(
        [px(0), px(0), px(1.0) - 1, px(1.0) - 1],
        outline=ink, width=round(length(BORDER)),
    )

    # 3) 모서리 블록 셋. 비어 있는 BR 이 회전 방향을 알려 준다.
    blocks = corner_blocks()
    for name in ("tl", "tr", "bl"):
        rect(blocks[name], fill=ink)

    # 4) 2톤 앵커. 채널별 게인·바닥값·화이트밸런스를 지우는 기준이다.
    #    측정면이 유채색이 되면서 역할이 하나 늘었다 — 채도를 재려면 세 채널이
    #    각각 보정돼 있어야 하는데, 흑·백 두 점이 그 보정을 채널별로 준다.
    for side in ("left", "right"):
        dark, light = anchor_rects(side)
        rect(dark, fill=ink)
        rect(light, fill=white)
        # 라미네이트 창 표시. 이 안쪽을 무광 필름으로 덮는다.
        x0 = min(dark[0], light[0]) - LAMINATE_PAD
        y0 = ANCHOR_Y - LAMINATE_PAD
        x1 = max(dark[2], light[2]) + LAMINATE_PAD
        y1 = ANCHOR_Y + ANCHOR + LAMINATE_PAD
        rect((x0, y0, x1, y1), outline=ink, width=max(1, round(length(0.0027))))

    # 5) POINT_ID
    font = load_font(round(length(ID_FONT)))
    d.text(
        (px((ID_BOX[0] + ID_BOX[2]) / 2), px((ID_BOX[1] + ID_BOX[3]) / 2)),
        point_id, font=font, fill=ink, anchor="mm",
    )

    # 6) 선군. 상시 지표가 아니라 감도 비교용이다.
    if probe:
        y = LINE_Y0
        for w in LINE_WIDTHS:
            rect((LINE_X[0], y, LINE_X[1], y + w), fill=ink)
            y += w + LINE_GAP

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, dpi=(300, 300))


def print_spec(tone: str) -> None:
    """판독기 규격에 옮겨 적을 좌표를 찍는다."""
    r, g, b = TONES[tone]
    print(f"캔버스 {CANVAS}  패드 {PAD}  원점 {ORIGIN}  바깥 여백 {QUIET}")
    print(f"  측정면 바탕색    {tone}  RGB({r}, {g}, {b})  #{r:02X}{g:02X}{b:02X}")
    print(f"  테두리 두께      {BORDER}")
    print(f"  측정 여백        {MARGIN}   (패드 면적의 "
          f"{(MARGIN[2] - MARGIN[0]) * (MARGIN[3] - MARGIN[1]) * 100:.0f}%)")
    blocks = corner_blocks()
    for side in ("left", "right"):
        dark, light = anchor_rects(side)
        print(f"  앵커 {side:<5} 어두움 {tuple(round(v, 4) for v in dark)}")
        print(f"  앵커 {side:<5} 밝음   {tuple(round(v, 4) for v in light)}")
    lam = LAMINATE_PAD
    left = anchor_rects("left")
    left_edge = min(r_[0] for r_ in left) - lam
    right_edge = max(r_[2] for r_ in left) + lam
    print(f"  블록~앵커 간격    {left_edge - blocks['tl'][2]:.4f}  "
          f"(라미네이트 표시선 기준)")
    print(f"  앵커~번호 간격    {ID_BOX[0] - right_edge:.4f}  "
          f"(라미네이트 표시선 기준)")
    print(f"  번호 글자 크기    {round(length(ID_FONT))}px")
    print(f"  선군 가로        {LINE_X}   "
          f"(BR 자리 {round(1 - BLOCK_OFFSET - BLOCK, 4)}~ 를 비움)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="assets/pad_chroma", help="출력 폴더")
    parser.add_argument(
        "--ids", nargs="+", default=["1088", "1089", "1090", "1091", "1092"],
        help="관측 포인트 번호. 유채색 시안은 기존 패드(1078~1087)와 따로 "
             "시험하므로 번호를 겹치지 않게 둔다.",
    )
    parser.add_argument(
        "--tone", default=DEFAULT_TONE, choices=sorted(TONES),
        help=f"측정면 바탕색 (기본 {DEFAULT_TONE})",
    )
    parser.add_argument("--no-probe", action="store_true", help="선군을 빼고 그린다")
    args = parser.parse_args(argv)

    out = Path(args.out)
    for tid in args.ids:
        draw_pad(tid, args.tone, out / f"pad_{tid}_{args.tone}.png",
                 probe=not args.no_probe)
    print_spec(args.tone)
    print(f"\n{len(args.ids)}장 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

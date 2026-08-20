"""참조 패드 도안 시안 — 2톤 앵커 방식.

``make_pad.py`` 의 도안을 실촬영에서 드러난 문제 세 가지에 맞춰 고친 것이다.
좌표는 전부 **패드 외곽 기준 정규화 [0, 1]** 로 두고 캔버스 픽셀로만 환산한다.
패드 크기(1120)와 기존 요소의 좌표는 그대로라, 판독기 규격에 앵커와 여백만
더하면 된다.

무엇을 고쳤나
-------------

1. **바깥 흰 여백을 두른다.**

   지금 도안은 검은 테두리가 패드 실물 가장자리까지 나가 있다. 그래서 벽이나
   바닥에 붙이면 테두리가 배경에 바로 닿는다. 배경에 어두운 것 — 요철 도장면의
   그늘, 패널 이음새, 패드가 벽에서 떠서 지는 그림자 — 이 둘레 어딘가에 있으면
   테두리가 그것과 한 덩어리가 되어 액자 모양을 잃고 검출이 실패한다.

   실촬영에서 갈린 지점이 정확히 이것이었다. 흰 종이 위에 인쇄된 패드는 테두리
   둘레 16점이 전부 배경보다 밝아 한 번도 실패하지 않았고, 테두리가 실물
   가장자리까지 나간 패드는 16점 중 9점이 어두워 셋 중 셋이 실패했다.

2. **2톤 앵커를 넣는다.** 아래 따로 적는다.

3. **선군이 빈 모서리 자리를 침범하지 않게 줄인다.**

   회전 방향은 네 모서리 중 비어 있는 한 곳으로 판정한다. 지금 도안은 선군이
   오른쪽 아래 자리를 절반 넘게 덮어, 빈 자리가 빈 것처럼 보이지 않는다. 실제로
   판정 마진이 개소마다 0.03까지 떨어졌다.

2톤 앵커가 무엇인가
-------------------

카메라가 읽는 값은 반사율에 비례하지 않는다. 대략 이렇다.

    관측값 = 바닥값 + 게인 x 조도 x 반사율

``바닥값`` 은 빛이 없어도 센서가 얹는 값이고, ``게인 x 조도`` 는 노출과 조명에
따라 매번 달라진다. 분진을 재려면 ``반사율`` 만 남겨야 한다.

지금은 **여백을 테두리로 나눈다.** 나눗셈은 ``게인 x 조도`` 를 지우지만
``바닥값`` 은 못 지운다. 분모에 바닥값이 섞여 있기 때문이다. 그런데 하필 분모가
검은 잉크라, 잉크가 어두울수록 바닥값이 분모의 대부분을 차지한다.

실촬영에서 이게 터졌다. 한 개소의 테두리가 0~255 척도에서 **4카운트**로 찍혔다.
다른 개소는 34~121 이었다. 4로 나누면 노이즈 1카운트가 결과를 20% 움직이고,
테두리를 따라 조명 기울기를 재려고 맞춘 평면은 잔차가 신호의 36%가 되어
의미를 잃는다. 기준 사진과 판독 사진이 서로 다른 배율로 증폭되니 빼도 안
지워지고, 남은 기울기가 그대로 오염도로 읽혔다.

**두 점을 쓰면 바닥값까지 사라진다.** 반사율을 아는 흑·백 패치를 하나씩 두고

    반사율 = (관측값 - 흑색패치) / (백색패치 - 흑색패치)

빼기가 바닥값을 지우고 나누기가 ``게인 x 조도`` 를 지운다. 분모가 흑백 차이라
충분히 크므로 노이즈에 휘둘리지도 않는다.

**대신 앵커에 분진이 앉으면 안 된다.** 앉으면 기준이 신호와 같이 움직여 서로
상쇄되고, 아무리 더러워져도 깨끗하다고 나온다. 그래서 앵커 자리에만 무광
라미네이트나 투명창을 덮는다. 도안에는 덮을 자리를 가는 선으로 표시해 둔다.
덮지 않은 패드에 이 방식을 쓰면 분진 신호가 조용히 사라지므로, 판독기 설정도
'보호됨' 으로 선언한 규격에서만 2점 보정을 쓴다.

앵커는 위쪽 밴드에 두 쌍 둔다. 한 쌍이 못 쓰게 돼도 나머지로 버티고, 좌우로
떨어뜨려 두면 앵커 자체에 밝기 차가 있는지도 드러난다.

    python assets/make_pad_dual_tones.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# 캔버스
# --------------------------------------------------------------------------

PAD = 1120
"""패드 외곽 한 변. 정규화 좌표 1.0 에 해당하는 픽셀 수. 기존 도안과 같다."""

QUIET = 0.125
"""패드 바깥에 두를 흰 여백. 패드 한 변 대비 비율.

테두리가 배경에 직접 닿지 않게 하는 것이 목적이다. 테두리 두께(0.059)의 두 배
남짓이면 배경이 어두워도 액자가 고립된다.
"""

ORIGIN = round(PAD * QUIET)
CANVAS = PAD + 2 * ORIGIN


def px(v: float) -> float:
    """정규화 좌표를 캔버스 픽셀로."""
    return ORIGIN + v * PAD


def length(v: float) -> float:
    return v * PAD


# --------------------------------------------------------------------------
# 규격 (정규화 좌표)
# --------------------------------------------------------------------------

BORDER = 0.0589
"""테두리 두께. 굵을수록 조명 기준값이 안정되고 꼭짓점 적합 표본이 는다."""

BLOCK = 0.0643
BLOCK_OFFSET = 0.0786
"""모서리 블록 크기와 패드 외곽에서의 거리. 기존 도안과 같다."""

TOP_BAND = (BORDER, 0.1750)
"""위쪽 인쇄 밴드. 모서리 블록, POINT_ID, 앵커가 여기 들어간다."""

ID_BOX = (0.3491, 0.0643, 0.6563, 0.1527)
"""POINT_ID 글자가 들어갈 자리. 기존 도안과 같다."""

ID_FONT = 132 / 1120
"""번호 글자 크기. 패드 한 변 대비 비율이다.

기존 도안(``make_pad.py``)이 1120px 패드에 132px 로 그린 것과 같은 값이다.
상자 높이에서 끌어내던 것을 이 값으로 바꿨다 - 그렇게 하면 글자가 기존
도안의 86% 로 작아졌고, 실촬영에서 글자 높이가 96px 대 82px 로 갈렸다.

작으면 획이 얇아져 이진화에서 글자가 붙거나 끊긴다. 실제로 1084 의 8 과 4 가
한 덩어리(폭 119px, 종횡비 1.43)로 붙어 118 로 읽혔고, 1085 는 획이 갉여
9111 로 읽혔다.
"""

ANCHOR = 0.0600
"""앵커 패치 한 변.

작을수록 조명 기울기의 영향을 덜 받고, 클수록 노이즈가 잘 평균된다. 판독은
중앙값을 쓰므로 가장자리 인쇄 번짐은 이 크기면 묻힌다. 260px 로 찍힌 패드에서
한 변이 약 16px 이라 중앙값을 낼 표본이 250개쯤 된다.

모서리 블록(0.0643)보다 조금 작게 잡았다. 번호 상자와의 간격을 벌리기 위해
줄인 것이다 - 아래 ID_CLEARANCE 를 보라.
"""

ANCHOR_GAP = 0.0120
"""흑·백 패치 사이 간격. 붙여 두면 인쇄 번짐으로 서로 물든다."""

ANCHOR_Y = 0.0786
"""앵커 패치 위쪽 y. 모서리 블록과 같은 줄에 놓아 밴드를 넓히지 않는다."""

LAMINATE_PAD = 0.0140
"""라미네이트 창 표시선이 앵커 바깥으로 물러날 거리."""

ID_CLEARANCE = 0.0300
"""라미네이트 표시선과 번호 상자 사이에 비워 둘 간격.

앵커 쌍을 빈 구간 한가운데 놓으면 양쪽이 0.019 씩 남는데, 그 정도로는 정합이
조금만 어긋나도 표시선이 번호 판독 영역으로 밀려 들어온다. 실촬영에서 그
선이 숫자 하나로 세어져 1086 이 21986 으로 읽혔다. 판독기가 홀쭉한 조각을
걸러 넘기지만 도안에서 떼어 놓는 편이 맞다.
"""

BLOCK_CLEARANCE = 0.0100
"""모서리 블록과 라미네이트 표시선 사이 최소 간격.

번호 쪽으로 간격을 벌리다 블록에 붙으면 이진화에서 한 덩어리가 된다.
"""

MARGIN = (BORDER, 0.1750, 1.0 - BORDER, 0.8036)
"""측정 여백. 인쇄물이 전혀 없는 구간이다. 패드 면적의 55%."""

LINE_X = (0.2589, 0.8400)
"""선군 가로 범위. 오른쪽 끝을 0.84 로 당겨 BR 모서리 자리(0.857~)를 비운다."""

LINE_Y0 = 0.8036
LINE_WIDTHS = (0.0027, 0.0063, 0.0134, 0.0286)
LINE_GAP = 0.0196
"""선군 4단. 굵기가 두 배씩 차이 난다. 얇은 선일수록 분진에 먼저 묻힌다."""


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
    """앵커 쌍의 시작 x.

    한가운데 놓지 않는다. 번호 상자 쪽으로 ``ID_CLEARANCE`` 를 먼저 확보하고
    남는 만큼 모서리 블록 쪽으로 민다. 양쪽을 똑같이 나누면 번호 쪽 간격이
    모자라 표시선이 판독 영역으로 밀려 들어온다.

    자리를 숫자로 박아 두지 않는다. 글자 폭이나 블록 크기를 조금만 바꿔도
    서로 붙어 버리므로 매번 계산한다.
    """
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

    왼쪽 쌍과 오른쪽 쌍의 흑백 순서를 뒤집는다. 좌우로 조명 기울기가 있으면
    두 쌍이 같은 순서일 때 흑백 차이에 그 기울기가 그대로 얹히는데, 뒤집어
    두면 평균에서 상쇄된다.
    """
    x0 = anchor_pair_x0(side)
    first = (x0, ANCHOR_Y, x0 + ANCHOR, ANCHOR_Y + ANCHOR)
    x1 = x0 + ANCHOR + ANCHOR_GAP
    second = (x1, ANCHOR_Y, x1 + ANCHOR, ANCHOR_Y + ANCHOR)
    return (first, second) if side == "left" else (second, first)


# --------------------------------------------------------------------------
# 렌더
# --------------------------------------------------------------------------

BUNDLED_FONT = Path(__file__).resolve().parent / "fonts" / "DejaVuSans-Bold.ttf"
"""저장소에 넣어 둔 폰트. 인쇄와 판독이 같은 파일을 쓴다.

앞서 후보 목록의 첫 줄이 리눅스 경로여서, 같은 코드가 리눅스에서는
DejaVuSans-Bold 로 윈도우에서는 Arial Bold 로 찍었다. 한 현장에 서로 다른
글꼴의 패드가 섞였고 Arial 이 더 얇아 획이 갉였다. 장비에 무엇이 깔려 있든
같은 글꼴이 나오도록 저장소 안의 파일을 먼저 본다.
"""

FONT_CANDIDATES = (
    str(BUNDLED_FONT),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def load_font(size: int) -> ImageFont.FreeTypeFont:
    """굵은 산세리프. 없으면 기본 폰트로 떨어진다.

    인쇄에 쓴 폰트를 판독기의 ``point_id.font_dir`` 에 같이 넣어야 번호
    판독이 맞는다. 여기서 고른 파일이 그 파일이다.
    """
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def draw_pad(point_id: str, tone: str, path: Path, probe: bool = True) -> None:
    """도안 한 장.

    ``tone`` 은 패드 바탕색이다. ``white`` = 백색 바탕/흑색 인쇄(흑색 분진용),
    ``black`` = 흑색 바탕/백색 인쇄(백색 분진용).
    """
    white, black = (255, 255, 255), (0, 0, 0)
    bg, ink = (white, black) if tone == "white" else (black, white)

    # 바깥 여백은 패드 바탕과 같은 색이다. 톤이 바뀌어도 테두리 잉크와
    # 배경 사이에는 늘 바탕색 띠가 놓인다.
    img = Image.new("RGB", (CANVAS, CANVAS), bg)
    d = ImageDraw.Draw(img)

    def rect(box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = box
        d.rectangle([px(x0), px(y0), px(x1), px(y1)],
                    fill=fill, outline=outline, width=width)

    # 1) 외곽 테두리 — 정합 기준점이자 조명 기준면.
    #    PIL 은 주어진 사각형의 **안쪽으로** 선을 채우므로, 패드 외곽을 그대로
    #    주면 잉크가 0 부터 BORDER 까지 놓인다.
    d.rectangle(
        [px(0), px(0), px(1.0) - 1, px(1.0) - 1],
        outline=ink, width=round(length(BORDER)),
    )

    # 2) 모서리 블록 셋. 비어 있는 BR 이 회전 방향을 알려 준다.
    blocks = corner_blocks()
    for name in ("tl", "tr", "bl"):
        rect(blocks[name], fill=ink)

    # 3) 2톤 앵커. 어두운 패치는 잉크색, 밝은 패치는 바탕색이다.
    #    바탕색 패치는 백색 패드에서는 인쇄하지 않은 자리 그대로가 된다.
    for side in ("left", "right"):
        dark, light = anchor_rects(side)
        rect(dark, fill=ink)
        rect(light, fill=bg)
        # 라미네이트 창 표시. 이 안쪽을 무광 필름으로 덮는다.
        x0 = min(dark[0], light[0]) - LAMINATE_PAD
        y0 = ANCHOR_Y - LAMINATE_PAD
        x1 = max(dark[2], light[2]) + LAMINATE_PAD
        y1 = ANCHOR_Y + ANCHOR + LAMINATE_PAD
        rect((x0, y0, x1, y1), outline=ink, width=max(1, round(length(0.0027))))

    # 4) POINT_ID
    font = load_font(round(length(ID_FONT)))
    d.text(
        (px((ID_BOX[0] + ID_BOX[2]) / 2), px((ID_BOX[1] + ID_BOX[3]) / 2)),
        point_id, font=font, fill=ink, anchor="mm",
    )

    # 5) 선군. 상시 지표가 아니라 감도 비교용이다.
    if probe:
        y = LINE_Y0
        for w in LINE_WIDTHS:
            rect((LINE_X[0], y, LINE_X[1], y + w), fill=ink)
            y += w + LINE_GAP

    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, dpi=(300, 300))


def print_spec() -> None:
    """판독기 규격에 옮겨 적을 좌표를 찍는다."""
    print(f"캔버스 {CANVAS}  패드 {PAD}  원점 {ORIGIN}  바깥 여백 {QUIET}")
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
    left_edge = min(r[0] for r in left) - lam
    right_edge = max(r[2] for r in left) + lam
    print(f"  블록~앵커 간격    {left_edge - blocks['tl'][2]:.4f}  "
          f"(라미네이트 표시선 기준)")
    print(f"  앵커~번호 간격    {ID_BOX[0] - right_edge:.4f}  "
          f"(라미네이트 표시선 기준)")
    print(f"  번호 글자 크기    {round(length(ID_FONT))}px  "
          f"(기존 도안과 같은 비율)")
    print(f"  선군 가로        {LINE_X}   (BR 자리 {round(1 - BLOCK_OFFSET - BLOCK, 4)}~ 를 비움)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="assets/pad_dual_tones", help="출력 폴더")
    parser.add_argument(
        "--ids", nargs="+", default=["1083", "1084", "1085", "1086", "1087"],
        help="관측 포인트 번호. 2톤 앵커 시안은 기존 패드(1078~1082)와 따로 "
             "시험하므로 번호를 겹치지 않게 둔다.",
    )
    parser.add_argument("--no-probe", action="store_true", help="선군을 빼고 그린다")
    args = parser.parse_args(argv)

    out = Path(args.out)
    for tid in args.ids:
        for tone in ("white", "black"):
            draw_pad(tid, tone, out / f"pad_{tid}_{tone}.png", probe=not args.no_probe)
    print_spec()
    print(f"\n{len(args.ids) * 2}장 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

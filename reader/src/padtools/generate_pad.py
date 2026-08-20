"""패드 도안 생성 CLI.

    python -m padtools.generate_pad --tone white --spec v2 --out pad.png

규격은 ``padreader.spec`` 이 단일 진실공급원이다. 여기서는 인자만 받는다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2

from padreader.render import render_pad
from padreader.spec import SPECS, get_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="참조 패드 도안 생성")
    parser.add_argument(
        "--tone", choices=("white", "black"), required=True,
        help="white = 백색 바탕/흑색 인쇄 (흑색 분진 포인트용)",
    )
    parser.add_argument(
        "--spec", choices=sorted(SPECS), default="v2",
        help="legacy = 샘플 도안 그대로, v2 = 선군 단축 + 앵커 자리, "
             "v2_protected = 앵커를 덮어 만든 패드용",
    )
    parser.add_argument("--id", dest="point_id", default="1078", help="POINT_ID 숫자")
    parser.add_argument("--pad-px", type=int, default=1120, help="패드 외곽 한 변 픽셀")
    parser.add_argument(
        "--font", default=None,
        help="POINT_ID 용 TTF 경로. 판독 설정과 같은 값을 써야 매칭이 성립한다",
    )
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    spec = get_spec(args.spec)
    image = render_pad(
        spec,
        tone=args.tone,
        point_id=args.point_id,
        pad_px=args.pad_px,
        font_path=args.font,
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(args.out), image):
        print(f"저장 실패: {args.out}", file=sys.stderr)
        return 1

    print(f"{args.out}  {image.shape[1]}x{image.shape[0]}  spec={args.spec} tone={args.tone}")
    if spec.has_anchors and not spec.anchors_protected:
        print(
            "  주의: 이 규격의 앵커는 보호되지 않은 것으로 선언되어 있어 조도\n"
            "  정규화가 테두리 단일 기준으로 동작한다. 앵커를 라미네이트 등으로\n"
            "  덮어 제작했다면 판독 시 spec 을 v2_protected 로 지정해야 한다.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

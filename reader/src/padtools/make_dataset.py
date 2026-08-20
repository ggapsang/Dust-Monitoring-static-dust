"""합성 검증 이미지 묶음 생성 CLI.

    python -m padtools.make_dataset --tone white --out data/synth --count 60

실촬영이 없는 동안 임계값 분포를 보고 판독기를 돌려보기 위한 것이다.
조건을 무작위로 흩뿌리지 않고 **축별로 쓸어** 만든다. 임계값을 정하려면
'무엇이 달라지면 어떤 지표가 움직이는가'를 봐야 하는데, 조건을 한꺼번에
흔들면 그걸 읽어낼 수 없기 때문이다.

파일 이름에 조건과 정답 피복률이 들어가므로, 판독 결과 CSV 와 이름으로
맞춰볼 수 있다.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import cv2

from padreader.spec import SPECS, get_spec

from .synth import CaptureParams, Clump, expected_soiling, synthesize, vary


def _sweeps(base: CaptureParams) -> list[tuple[str, CaptureParams]]:
    """축별 조건 목록. (이름, 파라미터)."""
    out: list[tuple[str, CaptureParams]] = []

    for coverage in (0.0, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5):
        out.append((f"dust{coverage:.2f}", vary(base, dust_coverage=coverage)))

    for tilt in (0, 10, 20, 30, 40):
        out.append((f"tilt{tilt:02d}", vary(base, dust_coverage=0.2, tilt_deg=tilt, pan_deg=35)))

    for fill in (0.25, 0.35, 0.55, 0.75):
        out.append((f"fill{fill:.2f}", vary(base, dust_coverage=0.2, pad_fill=fill)))

    for gradient, direction in ((0.0, 0), (0.2, 0), (0.35, 90), (0.35, 210)):
        out.append((
            f"light{gradient:.2f}d{direction:03d}",
            vary(base, dust_coverage=0.2, light_gradient=gradient, light_direction_deg=direction),
        ))

    for gain, black in ((1.0, 0), (0.8, 10), (0.6, 22)):
        out.append((f"gain{gain:.2f}b{black:02d}", vary(base, dust_coverage=0.2, gain=gain, black_level=black)))

    for blur in (0.0, 1.5, 3.0, 6.0):
        out.append((f"blur{blur:.1f}", vary(base, dust_coverage=0.2, blur_sigma=blur)))

    for quarter in range(4):
        out.append((f"rot{quarter * 90:03d}", vary(base, dust_coverage=0.2, quarter_turns=quarter)))

    clumps = (
        Clump(x=0.35, y=0.45, sigma=0.05, coverage=0.8),
        Clump(x=0.62, y=0.55, sigma=0.04, coverage=0.7),
    )
    out.append(("clumped", vary(base, dust_coverage=0.0, clumps=clumps)))
    out.append(("clumped_on_uniform", vary(base, dust_coverage=0.1, clumps=clumps)))

    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="합성 검증 이미지 생성")
    parser.add_argument("--tone", choices=("white", "black"), required=True)
    parser.add_argument("--spec", choices=sorted(SPECS), default="v2_protected")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--id", dest="point_id", default="1078")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--noise", type=float, default=1.0)
    parser.add_argument("--jpeg", type=int, default=None, help="JPEG 품질 (생략하면 PNG)")
    args = parser.parse_args(argv)

    spec = get_spec(args.spec)
    base = CaptureParams(
        pad_fill=0.55, black_level=10, gain=0.95, noise_sigma=args.noise,
        jpeg_quality=args.jpeg, seed=args.seed,
    )

    args.out.mkdir(parents=True, exist_ok=True)
    manifest = []

    for index, (name, params) in enumerate(_sweeps(base)):
        image, corners = synthesize(spec, args.tone, params, point_id=args.point_id)
        filename = f"{index:03d}_{args.tone}_{name}.png"
        cv2.imwrite(str(args.out / filename), image)
        manifest.append({
            "file": filename,
            "tone": args.tone,
            "spec": args.spec,
            "expected_soiling": expected_soiling(args.tone, params.dust_coverage),
            "corners": corners.tolist(),
            "params": asdict(params),
        })

    manifest_path = args.out / f"manifest_{args.tone}.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(manifest)}장 -> {args.out}")
    print(f"정답 매니페스트: {manifest_path}")
    print("\n주의: 합성은 padtools.synth 가 주입한 모델을 되돌려줄 뿐이다.")
    print("테두리 조명 추정의 실제 정밀도나 흑/백 패드의 정밀도 비대칭은")
    print("실촬영으로만 판정된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

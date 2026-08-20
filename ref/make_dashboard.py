"""대시보드 표본 데이터 생성.

``assets/samples/`` 의 실촬영 사진을 판독해 대시보드가 읽을 데이터와 이미지를
만든다. AMR 이 아직 돌지 않으므로 대시보드가 보여줄 것이 없는데, 판독기는
이미 돌고 있으니 그 결과를 그대로 표본으로 쓴다.

폴더 하나가 관측 포인트 하나다. 그 안의 ``*baseline*`` 이 부착 직후 기준
사진이고, ``*test_NN*`` 이 순회 회차다. 회차 번호 순으로 늘어놓으면 한
개소의 시계열이 된다.

출력을 JSON 이 아니라 ``data.js`` 로 쓴다. 대시보드를 파일로 직접 열면
브라우저가 fetch 를 막아 JSON 을 못 읽는데, 스크립트 태그는 막히지 않는다.

    python -m padtools.dashboard
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2

from padreader.config import Config, load_config
from padreader.pipeline import read_pad

THUMB_PX = 640
"""저장할 이미지 한 변. 원본 정합 크기는 1120 이지만 화면에서 그만큼 쓰지
않는다. 저장소에 들어갈 용량을 줄인다."""

JPEG_QUALITY = 86


def _sets(root: Path) -> list[tuple[str, Path, list[Path]]]:
    """(포인트 이름, 기준 사진, 회차 사진들). 회차는 이름 순."""
    out: list[tuple[str, Path, list[Path]]] = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        images = sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.png"))
        baseline = next((p for p in images if "baseline" in p.stem.lower()), None)
        if baseline is None:
            continue
        readings = [p for p in images if p != baseline]
        if readings:
            out.append((folder.name, baseline, readings))
    return out


def _write_image(image, path: Path) -> str:
    """정합 이미지를 줄여 저장하고 대시보드가 쓸 상대 경로를 돌려준다."""
    thumb = cv2.resize(image, (THUMB_PX, THUMB_PX), interpolation=cv2.INTER_AREA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), thumb, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return f"img/{path.name}"


def _reading_entry(
    index: int, source: Path, result, img_dir: Path, point: str
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "seq": index,
        "source": source.name,
        "success": result.success,
        "elapsed_ms": round(result.elapsed_ms or 0.0, 1),
    }

    if not result.success:
        entry["failure_reason"] = (
            result.failure_reason.value if result.failure_reason else None
        )
        entry["failure_detail"] = result.failure_detail
        return entry

    entry["scores"] = {
        "uniform": round(result.scores.uniform, 4),
        "localized": round(result.scores.localized, 4),
        "combined": round(result.scores.combined, 4),
    }
    entry["point_id"] = result.point_id
    entry["quality"] = {
        "sharpness": round(result.quality.edge_rise_ratio or 0.0, 5),
        "saturated_ratio": round(result.quality.saturated_bright_ratio or 0.0, 5),
        "pad_size_px": round(result.quality.pad_size_px or 0.0, 1),
        "pad_size_diff_ratio": round(result.pad_size_diff_ratio or 0.0, 4),
    }
    entry["excluded_px"] = result.excluded_px
    entry["images"] = {
        "rectified": _write_image(
            result.rectified, img_dir / f"{point}_{index:02d}_rectified.jpg"
        ),
        "distribution": _write_image(
            result.distribution, img_dir / f"{point}_{index:02d}_distribution.jpg"
        ),
    }
    return entry


def build(root: Path, out_dir: Path, tone: str, cfg: Config) -> dict[str, Any]:
    """표본 전체를 판독해 대시보드 데이터를 만든다."""
    img_dir = out_dir / "img"
    if img_dir.exists():
        # 표본이 빠지면 옛 이미지가 남아 화면에 섞인다. 매번 새로 만든다.
        shutil.rmtree(img_dir)

    points: list[dict[str, Any]] = []
    for name, baseline, readings in _sets(root):
        point: dict[str, Any] = {
            "id": name.split("_")[0],
            "set": name,
            "tone": tone,
            "baseline_source": baseline.name,
            "readings": [],
        }

        for index, source in enumerate(readings, start=1):
            print(f"  {name} {source.name}", flush=True)
            result = read_pad(str(source), str(baseline), tone, cfg, visualize=True)

            # 기준 정합 사진은 개소마다 한 장이면 된다. 회차마다 같은 것이
            # 다시 나오므로 첫 회차에서만 받아 둔다.
            if index == 1 and result.baseline_rectified is not None:
                point["baseline_image"] = _write_image(
                    result.baseline_rectified, img_dir / f"{point['id']}_baseline.jpg"
                )

            point["readings"].append(
                _reading_entry(index, source, result, img_dir, point["id"])
            )

        points.append(point)

    return {
        # 화면에 그대로 찍히므로 윈도우 역슬래시를 쓰지 않는다.
        "source": root.as_posix(),
        "tone": tone,
        "config": asdict(cfg),
        "points": points,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--samples", default="assets/samples", help="표본 폴더 (기본 assets/samples)"
    )
    parser.add_argument(
        "--out", default="dashboard", help="출력 폴더 (기본 dashboard)"
    )
    parser.add_argument("--tone", default="white", choices=("white", "black"))
    parser.add_argument("--config", default=None, help="설정 파일 경로")
    args = parser.parse_args(argv)

    root = Path(args.samples)
    if not root.is_dir():
        parser.error(f"표본 폴더가 없다: {root}")

    out_dir = Path(args.out)
    cfg = load_config(args.config)

    print(f"표본 판독 시작: {root}")
    data = build(root, out_dir, args.tone, cfg)

    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "data.js"
    body = json.dumps(data, ensure_ascii=False, indent=1)
    target.write_text(
        "// padtools.dashboard 가 만든 파일이다. 직접 고치지 않는다.\n"
        "window.PADDATA = " + body + ";\n",
        encoding="utf-8",
    )

    total = sum(len(p["readings"]) for p in data["points"])
    print(f"완료: 개소 {len(data['points'])}, 회차 {total} -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

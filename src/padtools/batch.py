"""폴더 일괄 판독 CLI.

    python -m padtools.batch images/ --tone white --csv out.csv
    python -m padtools.batch images/ --tone white --set grid.rows=4 --set score.statistic=max

임계값이 아직 정해지지 않은 단계라, 같은 이미지 묶음을 설정만 바꿔가며
반복해서 읽고 분포를 보는 일이 계속 생긴다. 그 루프를 짧게 만드는 것이
이 도구의 목적이다.

산출값은 게이트 통과 여부와 무관하게 항상 나오므로, 임계값을 비워 둔 채로
한 번 돌려 분포를 본 뒤 값을 정하면 된다.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from padreader.config import load_config
from padreader.pipeline import read_pad

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

COLUMNS = [
    "file",
    "success",
    "failure_reason",
    "dust_score",
    "stdev",
    "iqr",
    "p90_minus_p50",
    "excluded_count",
    "target_id",
    "target_id_status",
    "target_id_confidence",
    "rotation_deg",
    "rotation_margin",
    "edge_rise_ratio",
    "tenengrad",
    "saturated_bright_ratio",
    "saturated_dark_ratio",
    "tilt_deg",
    "pad_size_px",
    "anchor_contrast",
    "normalize_method",
    "plane_residual_rms",
    "plane_condition_number",
    "elapsed_ms",
]


def _parse_setting(text: str) -> tuple[list[str], Any]:
    """``grid.rows=4`` 를 (경로, 값) 으로. 값은 YAML 규칙으로 해석한다."""
    if "=" not in text:
        raise argparse.ArgumentTypeError(f"--set 은 key=value 형식이어야 한다: {text!r}")
    key, _, raw = text.partition("=")

    import yaml

    return key.strip().split("."), yaml.safe_load(raw)


def _nest(pairs: list[tuple[list[str], Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, value in pairs:
        node = out
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = value
    return out


def _row(path: Path, result) -> dict[str, Any]:
    payload = result.to_dict(include_cells=False)
    quality = payload["quality"]
    normalization = payload["normalization"]
    dispersion = payload["dispersion"]
    return {
        "file": path.name,
        "success": result.success,
        "failure_reason": payload["failure_reason"],
        "dust_score": payload["dust_score"],
        "stdev": dispersion["stdev"],
        "iqr": dispersion["iqr"],
        "p90_minus_p50": dispersion["p90_minus_p50"],
        "excluded_count": payload["excluded_count"],
        "target_id": payload["target_id"],
        "target_id_status": payload["target_id_status"],
        "target_id_confidence": payload["target_id_confidence"],
        "rotation_deg": payload["rotation_deg"],
        "rotation_margin": payload["rotation_margin"],
        "edge_rise_ratio": quality["edge_rise_ratio"],
        "tenengrad": quality["tenengrad"],
        "saturated_bright_ratio": quality["saturated_bright_ratio"],
        "saturated_dark_ratio": quality["saturated_dark_ratio"],
        "tilt_deg": quality["tilt_deg"],
        "pad_size_px": quality["pad_size_px"],
        "anchor_contrast": quality["anchor_contrast"],
        "normalize_method": normalization["method"],
        "plane_residual_rms": normalization["plane_residual_rms"],
        "plane_condition_number": normalization["plane_condition_number"],
        "elapsed_ms": payload["elapsed_ms"],
    }


def _summarize(rows: list[dict[str, Any]]) -> None:
    """임계값을 정하려면 분포를 봐야 한다. 주요 지표만 요약해 보여준다."""
    total = len(rows)
    ok = [r for r in rows if r["success"]]
    print(f"\n{total}장 중 {len(ok)}장 판독 성공")

    failures: dict[str, int] = {}
    for row in rows:
        if not row["success"]:
            failures[row["failure_reason"]] = failures.get(row["failure_reason"], 0) + 1
    for reason, count in sorted(failures.items(), key=lambda kv: -kv[1]):
        print(f"  {reason}: {count}")

    if not ok:
        return

    print(f"\n{'지표':<24}{'최소':>12}{'중앙':>12}{'최대':>12}")
    for column in (
        "dust_score", "iqr", "p90_minus_p50", "edge_rise_ratio", "tenengrad",
        "saturated_bright_ratio", "tilt_deg", "pad_size_px", "rotation_margin",
        "plane_residual_rms", "elapsed_ms",
    ):
        values = [r[column] for r in ok if isinstance(r[column], (int, float))]
        if not values:
            continue
        print(
            f"{column:<24}{min(values):>12.4g}"
            f"{statistics.median(values):>12.4g}{max(values):>12.4g}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="폴더 일괄 판독")
    parser.add_argument("directory", type=Path)
    parser.add_argument("--tone", choices=("white", "black"), required=True)
    parser.add_argument("--csv", type=Path, default=None, help="결과를 쓸 CSV 경로")
    parser.add_argument("--config", type=Path, default=None, help="설정 YAML 경로")
    parser.add_argument(
        "--set", dest="settings", action="append", type=_parse_setting, default=[],
        help="설정 덮어쓰기. 예: --set grid.rows=4 --set quality.max_tilt_deg=25",
    )
    parser.add_argument("--timing", action="store_true", help="처리 시간만 요약")
    args = parser.parse_args(argv)

    if not args.directory.is_dir():
        print(f"디렉터리가 아니다: {args.directory}", file=sys.stderr)
        return 1

    paths = sorted(
        p for p in args.directory.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES
    )
    if not paths:
        print(f"이미지가 없다: {args.directory}", file=sys.stderr)
        return 1

    config = load_config(args.config)
    overrides = _nest(args.settings)

    rows: list[dict[str, Any]] = []
    started = time.perf_counter()
    for index, path in enumerate(paths, 1):
        result = read_pad(path, args.tone, config=config, overrides=overrides)
        rows.append(_row(path, result))
        if not args.timing:
            score = result.dust_score
            shown = f"{score:.4f}" if score is not None else result.failure_reason.value
            print(f"[{index}/{len(paths)}] {path.name}: {shown}")

    wall = time.perf_counter() - started
    _summarize(rows)
    print(f"\n총 {wall:.2f}초, 장당 평균 {wall / len(paths) * 1000:.0f}ms")

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV: {args.csv}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

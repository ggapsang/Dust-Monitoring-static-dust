"""DB 와 파일 저장소가 맞는지 본다.

경로만 DB 에 두고 실물은 볼륨에 두는 구조라 둘이 어긋날 수 있다. 어긋나면
판독할 때가 되어서야 드러나는데, 그때는 사진을 이미 올린 뒤라 원인을 찾기
번거롭다. 기동할 때 한 번 훑어 로그와 ``/healthz`` 에 낸다.

고치지는 않는다. 없는 파일을 만들 수는 없고, 주인 없는 파일을 지우는 것은
사람이 판단할 일이다 - 방금 손으로 넣어 둔 것일 수도 있다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Baseline, Capture, Reading

TRACKED = ("baselines", "captures")
"""대조할 폴더. 결과 이미지는 판독 건에 딸린 것이라 따로 센다."""


def audit(session: Session, root: Path) -> dict[str, Any]:
    """(DB 에 있는데 없는 파일, 아무도 안 가리키는 파일)."""
    known: set[str] = set()
    missing: list[str] = []

    for row in session.execute(select(Baseline)).scalars():
        known.add(row.file_path)
        if not (root / row.file_path).is_file():
            missing.append(f"baseline {row.id} ({row.point_id}): {row.file_path}")
    for row in session.execute(select(Capture)).scalars():
        known.add(row.file_path)
        if not (root / row.file_path).is_file():
            missing.append(f"capture {row.id}: {row.file_path}")
    for row in session.execute(select(Reading)).scalars():
        for path in (row.img_baseline_rectified, row.img_rectified, row.img_distribution):
            if not path:
                continue
            known.add(path)
            if not (root / path).is_file():
                missing.append(f"reading {row.id}: {path}")

    orphans: list[str] = []
    for folder in TRACKED:
        base = root / folder
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            stored = path.relative_to(root).as_posix()
            # 쓰다 만 파일은 주인이 없는 게 정상이다. 다음 쓰기에서 덮인다.
            if stored.endswith(".part"):
                continue
            if stored not in known:
                orphans.append(stored)

    return {
        "missing_files": missing,
        "orphan_files": orphans,
        "in_sync": not missing and not orphans,
    }

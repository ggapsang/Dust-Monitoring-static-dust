"""파일 저장.

DB 에는 경로만 둔다. 파일은 공유 볼륨에 쓴다 - 판독 요청이 업로드 본문이
아니라 경로로 나가므로, ``padservice`` 가 같은 경로에서 같은 파일을 열 수
있어야 한다.

    /data/baselines/<POINT_ID>/<baseline_id>.<ext>
    /data/captures/<촬영일자>/<capture_id>.<ext>
    /data/results/<reading_id>/{baseline_rectified,rectified,distribution}.png

저장명은 DB 의 식별자로 짓고 사람이 붙인 원본 파일명은 컬럼에 그대로
남긴다. 사람이 읽는 이름과 시스템이 거는 이름을 섞으면, 같은 이름이 두 번
올라왔을 때 덮어쓰거나 이름을 바꿔야 한다.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

SAFE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
"""받을 확장자. 판독기가 OpenCV 로 여는 것들이다."""


def suffix_of(filename: str, default: str = ".jpg") -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name:
        return default
    suffix = "." + name.rsplit(".", 1)[1].lower()
    return suffix if suffix in SAFE_SUFFIXES else default


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def baseline_path(root: Path, point_id: str, baseline_id: int, suffix: str) -> Path:
    return root / "baselines" / _safe(point_id) / f"{baseline_id}{suffix}"


def capture_path(root: Path, captured_at: datetime, capture_id: int, suffix: str) -> Path:
    return root / "captures" / captured_at.strftime("%Y%m%d") / f"{capture_id}{suffix}"


def result_dir(root: Path, reading_id: int) -> Path:
    return root / "results" / str(reading_id)


def relative(root: Path, path: Path) -> str:
    """DB 에 넣을 경로. 볼륨 안 상대 경로로 둔다.

    절대 경로를 넣으면 마운트 지점이 바뀌는 순간 과거 기록이 전부 못 쓰게
    된다. 읽을 때 루트를 붙인다.
    """
    return path.relative_to(root).as_posix()


def absolute(root: Path, stored: str) -> Path:
    return root / stored


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _safe(value: str) -> str:
    """경로 조각으로 쓸 수 있게 다듬는다. 식별자가 경로를 벗어나지 못하게."""
    cleaned = "".join(ch for ch in value if ch.isalnum() or ch in "-_")
    return cleaned or "unknown"

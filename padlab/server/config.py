"""환경 설정.

판독 서비스 주소와 DB 접속 정보를 환경변수로 받는다. 기본값을 두지 않는
항목이 있는 이유는, 붙을 곳을 못 찾은 채 기동해 봐야 첫 요청에서 깨지기
때문이다. 기동 시점에 실패하는 편이 낫다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    padservice_url: str
    data_dir: Path
    request_timeout_sec: float
    concurrency: int

    @property
    def baselines_dir(self) -> Path:
        return self.data_dir / "baselines"

    @property
    def captures_dir(self) -> Path:
        return self.data_dir / "captures"

    @property
    def results_dir(self) -> Path:
        return self.data_dir / "results"


def load_settings() -> Settings:
    url = os.environ.get("PADLAB_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "PADLAB_DATABASE_URL 이 없다. "
            "예: postgresql+psycopg://padlab:padlab@postgres:5432/padlab"
        )

    # 판독 사진 경로를 padservice 에 문자열로 넘기므로, 두 컨테이너가 같은
    # 경로에 같은 볼륨을 붙이고 있어야 한다. 다르면 판독이 404 로 떨어진다.
    data_dir = Path(os.environ.get("PADLAB_DATA_DIR", "/data"))

    return Settings(
        database_url=url,
        padservice_url=os.environ.get("PADLAB_PADSERVICE_URL", "http://padreader:8911"),
        data_dir=data_dir,
        request_timeout_sec=float(os.environ.get("PADLAB_TIMEOUT_SEC", "120")),
        # 판독은 CPU 바운드다. 늘려도 선형으로 빨라지지 않고 서로 느려지기만
        # 하므로 기본을 낮게 둔다.
        concurrency=int(os.environ.get("PADLAB_CONCURRENCY", "2")),
    )

"""판독 실험 관리 서버.

판독 자체는 하지 않는다. ``padservice`` 에 경로를 넘겨 부르고, 결과와
이미지를 영속 저장하고, 쌓인 것을 조회하게 한다. 판독 모듈은 무상태 순수
함수로 두고 시계열·기준 관리·식별자 대응·화면은 전부 이쪽이 맡는다.

기동할 때 ``padservice`` 의 ``/healthz`` 와 ``/config`` 를 확인하고 실패하면
기동하지 않는다. 붙을 곳을 못 찾은 채 떠 있어 봐야 첫 판독에서 깨지는데,
그때는 사진을 이미 올린 뒤라 원인을 찾기 번거롭다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import api_readings, api_registry, api_runs
from .audit import audit
from .config import load_settings
from .db import apply_migrations, make_engine, make_session_factory
from .deps import get_root
from .reader import ReaderClient

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    engine = make_engine(settings.database_url)
    applied = apply_migrations(engine)

    client = ReaderClient(settings.padservice_url, settings.request_timeout_sec)
    health = await client.healthz()
    config = await client.config()

    for folder in (settings.baselines_dir, settings.captures_dir, settings.results_dir):
        folder.mkdir(parents=True, exist_ok=True)

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.client = client
    app.state.reader_health = health
    app.state.reader_config = config
    app.state.migrations = applied

    # DB 와 파일 저장소가 맞는지 기동할 때 한 번 훑는다. 어긋난 채로 돌면
    # 판독할 때가 되어서야 드러나는데, 그때는 사진을 이미 올린 뒤다.
    with app.state.session_factory() as session:
        app.state.audit = audit(session, settings.data_dir)
    report = app.state.audit
    if report["in_sync"]:
        print("[padlab] 저장소 점검: DB 와 파일이 맞는다")
    else:
        print(
            f"[padlab] 저장소 점검: 파일 없음 {len(report['missing_files'])}건, "
            f"주인 없는 파일 {len(report['orphan_files'])}건"
        )
        for line in report["missing_files"][:20] + report["orphan_files"][:20]:
            print(f"[padlab]   {line}")

    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(
    title="참조 패드 판독 실험 관리",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_registry.router)
app.include_router(api_runs.router)
app.include_router(api_readings.router)


@app.get("/healthz", tags=["운영"], summary="기동 확인")
def healthz() -> dict[str, Any]:
    """기동 여부와 저장소 점검 결과.

    점검은 기동할 때 한 번 한 것이다. 경로만 DB 에 두고 실물은 볼륨에 두는
    구조라 둘이 어긋날 수 있어, 어긋났으면 여기서 바로 보이게 한다.
    """
    report = getattr(app.state, "audit", None) or {}
    return {
        "status": "ok",
        "storage_in_sync": report.get("in_sync"),
        "missing_files": report.get("missing_files", []),
        "orphan_files": report.get("orphan_files", []),
    }


@app.get("/api/reader/config", tags=["운영"], summary="판독기 적용 설정")
def reader_config() -> dict[str, Any]:
    """판독 서비스가 지금 무슨 값으로 돌고 있는지.

    실증에서 임계값이 계속 바뀌므로 화면에서 확인할 수 있어야 한다. 기동
    시점에 받아 둔 값이며, 판독기 설정을 여기서 바꾸지는 않는다.
    """
    return app.state.reader_config


@app.get("/files/{stored:path}", include_in_schema=False)
def get_file(stored: str, root: Annotated[Path, Depends(get_root)]) -> FileResponse:
    """저장된 사진과 결과 이미지. DB 에는 상대 경로만 있고 여기서 루트를 붙인다."""
    return api_readings._serve(stored, root)


if WEB_DIR.is_dir():
    # 화면을 따로 띄우지 않고 여기서 같이 낸다. 같은 출처라 CORS 가 필요
    # 없고, 내부망 단일 인스턴스에 서비스를 하나 더 두는 만큼의 값이 없다.
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

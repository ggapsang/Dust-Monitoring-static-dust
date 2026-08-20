"""요청마다 넘겨줄 것들.

설정과 엔진은 기동 때 한 번 만들어 앱 상태에 둔다. 라우터는 그것을 여기서
꺼내 쓴다 - 모듈 전역에 두면 테스트에서 갈아 끼울 수가 없다.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from .config import Settings
from .reader import ReaderClient


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_root(request: Request) -> Path:
    return request.app.state.settings.data_dir


def get_client(request: Request) -> ReaderClient:
    return request.app.state.client


def get_session_factory(request: Request) -> Any:
    return request.app.state.session_factory


def get_concurrency(request: Request) -> int:
    return request.app.state.settings.concurrency


def get_session(request: Request) -> Iterator[Session]:
    factory = request.app.state.session_factory
    with factory() as session:
        yield session

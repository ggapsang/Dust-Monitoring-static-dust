"""DB 연결과 스키마 적용.

마이그레이션 도구를 두지 않는다. 실증용 단일 인스턴스이고 스키마가 한
파일이라, 기동할 때 ``CREATE TABLE IF NOT EXISTS`` 를 그대로 흘리는 편이
도구를 얹는 것보다 고장 날 곳이 적다.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def make_engine(url: str) -> Engine:
    # pool_pre_ping 을 켠다. DB 가 먼저 재시작되면 죽은 커넥션이 풀에 남아
    # 다음 요청이 이유 없이 실패한다.
    return create_engine(url, pool_pre_ping=True, future=True)


def apply_migrations(engine: Engine) -> list[str]:
    """``migrations/`` 의 SQL 을 이름 순으로 적용하고 적용한 파일명을 돌려준다."""
    applied: list[str] = []
    with engine.begin() as conn:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(text(path.read_text(encoding="utf-8")))
            applied.append(path.name)
    return applied


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)

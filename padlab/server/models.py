"""테이블 매핑.

컬럼 설명은 ``migrations/001_init.sql`` 에 있다. 두 군데에 같은 설명을 두면
어긋나므로 여기서는 되풀이하지 않는다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Target(Base):
    __tablename__ = "target"

    target_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    location_desc: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Point(Base):
    __tablename__ = "point"

    point_id: Mapped[str] = mapped_column(Text, primary_key=True)
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("target.target_id"))
    name: Mapped[str | None] = mapped_column(Text)
    location_desc: Mapped[str | None] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(String(8))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Baseline(Base):
    __tablename__ = "baseline"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    point_id: Mapped[str] = mapped_column(Text, ForeignKey("point.point_id"))
    file_path: Mapped[str] = mapped_column(Text)
    original_name: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_hint: Mapped[int | None] = mapped_column(Integer)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Capture(Base):
    __tablename__ = "capture"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    target_id: Mapped[str] = mapped_column(Text, ForeignKey("target.target_id"))
    file_path: Mapped[str] = mapped_column(Text)
    original_name: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class Run(Base):
    __tablename__ = "run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_override: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_run_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("run.id"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    total_captures: Mapped[int] = mapped_column(Integer)
    done_captures: Mapped[int] = mapped_column(Integer)
    notes: Mapped[list[Any]] = mapped_column(JSONB)


class Reading(Base):
    __tablename__ = "reading"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("run.id"))
    capture_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("capture.id"))
    baseline_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("baseline.id"))
    point_id: Mapped[str | None] = mapped_column(Text, ForeignKey("point.point_id"))
    pad_index: Mapped[int] = mapped_column(Integer)
    tone: Mapped[str] = mapped_column(String(8))

    success: Mapped[bool] = mapped_column(Boolean)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    failure_detail: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)

    score_uniform: Mapped[float | None] = mapped_column(Float)
    score_localized: Mapped[float | None] = mapped_column(Float)
    score_combined: Mapped[float | None] = mapped_column(Float)
    quality_sharpness: Mapped[float | None] = mapped_column(Float)
    quality_saturated_ratio: Mapped[float | None] = mapped_column(Float)
    quality_pad_size_px: Mapped[float | None] = mapped_column(Float)
    quality_pad_size_diff_ratio: Mapped[float | None] = mapped_column(Float)
    read_point_id: Mapped[str | None] = mapped_column(Text)
    elapsed_ms: Mapped[float | None] = mapped_column(Float)

    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    img_baseline_rectified: Mapped[str | None] = mapped_column(Text)
    img_rectified: Mapped[str | None] = mapped_column(Text)
    img_distribution: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

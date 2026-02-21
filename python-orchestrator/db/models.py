"""SQLAlchemy ORM models for VoxVault session storage (RFC-001 Proposta A)."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Session(Base):
    """Represents a recording/transcription session."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    participants: Mapped[str] = mapped_column(Text, default="[]")  # JSON array
    language_detected: Mapped[str] = mapped_column(String(10), default="auto")
    language_target: Mapped[str] = mapped_column(String(10), default="pt")
    transcript_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    minutes_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)


class ActionItem(Base):
    """Task/action item extracted from a session's meeting minutes."""

    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(36))
    owner: Mapped[str] = mapped_column(String(100), default="")
    task: Mapped[str] = mapped_column(Text)
    due_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, default=False)

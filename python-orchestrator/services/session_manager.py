"""Session lifecycle management — tracks state, buffers transcript chunks, persists to SQLite."""

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_session_factory
from db.models import Session
from models.schemas import SessionInfo, TranslatedChunk

logger = logging.getLogger(__name__)


class SessionManager:
    """Manages the current recording session state and transcript buffer."""

    def __init__(self):
        self.current_session: SessionInfo | None = None
        self.transcript_buffer: list[TranslatedChunk] = []
        self._started_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.current_session is not None

    async def start_session(
        self, title: str = "", participants: list[str] | None = None
    ) -> SessionInfo:
        """Start a new recording session."""
        if self.is_active:
            logger.warning("Session already active, stopping previous session first")
            await self.end_session()

        session_id = str(uuid.uuid4())
        now = datetime.utcnow()
        self._started_at = now

        self.current_session = SessionInfo(
            id=session_id,
            title=title or f"Meeting {now.strftime('%Y-%m-%d %H:%M')}",
            started_at=now,
            participants=participants or [],
            is_active=True,
        )
        self.transcript_buffer = []

        logger.info(f"Session started: {self.current_session.id} - {self.current_session.title}")
        return self.current_session

    async def add_chunk(self, chunk: TranslatedChunk) -> None:
        """Add a translated transcript chunk to the buffer."""
        if not self.is_active:
            return
        self.transcript_buffer.append(chunk)

    async def end_session(self) -> tuple[SessionInfo | None, str]:
        """End the current session. Returns (session_info, full_transcript_text)."""
        if not self.is_active or not self.current_session:
            return None, ""

        session = self.current_session
        session.is_active = False

        # Calculate duration
        duration = 0
        if self._started_at:
            duration = int((datetime.utcnow() - self._started_at).total_seconds())

        # Build full transcript text
        transcript_text = self.get_full_transcript()

        # Persist to SQLite
        try:
            factory = get_session_factory()
            async with factory() as db:
                db_session = Session(
                    id=session.id,
                    title=session.title,
                    started_at=session.started_at,
                    ended_at=datetime.utcnow(),
                    duration_seconds=duration,
                    participants=json.dumps(session.participants),
                    chunk_count=len(self.transcript_buffer),
                )
                db.add(db_session)
                await db.commit()
                logger.info(f"Session {session.id} persisted to database")
        except Exception as e:
            logger.error(f"Failed to persist session: {e}")

        # Reset state
        self.current_session = None
        self._started_at = None

        return session, transcript_text

    def get_full_transcript(self) -> str:
        """Get the accumulated transcript as formatted text."""
        lines = []
        for chunk in self.transcript_buffer:
            if chunk.original_text == chunk.translated_text:
                lines.append(f"[{chunk.source_language.upper()}] {chunk.original_text}")
            else:
                lines.append(f"[{chunk.source_language.upper()}] {chunk.original_text}")
                lines.append(f"[{chunk.target_language.upper()}] {chunk.translated_text}")
            lines.append("")
        return "\n".join(lines)

    def get_chunk_count(self) -> int:
        """Get the number of transcript chunks in the current session."""
        return len(self.transcript_buffer)

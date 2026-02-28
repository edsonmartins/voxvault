"""VoxVault Python Orchestrator — FastAPI application.

Connects to the Rust core via WebSocket, processes transcripts (translation),
and exposes SSE + REST endpoints for the Tauri frontend.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import settings
from db.database import init_db
from models.schemas import (
    MinutesRequest,
    MinutesResponse,
    SessionInfo,
    SessionStartRequest,
    SessionStopResponse,
    SettingsResponse,
    SettingsUpdateRequest,
    TranslatedChunk,
)
from services.minutes_generator import MinutesGenerator
from services.sentence_merger import SentenceMerger
from services.session_manager import SessionManager
from services.translation import TranslationService, create_translation_service
from services.ws_client import RustBridgeClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("voxvault")

# --- Global services ---

ws_client = RustBridgeClient(settings.rust_ws_url)
translator: TranslationService = create_translation_service(
    mode=settings.translation_mode,
    anthropic_api_key=settings.anthropic_api_key,
    openai_api_key=settings.openai_api_key,
    openrouter_api_key=settings.openrouter_api_key,
    openrouter_model=settings.openrouter_model,
    gemma_model_path=settings.gemma_model_path,
)
session_mgr = SessionManager()
sentence_merger = SentenceMerger(
    timeout_ms=settings.sentence_merge_timeout_ms,
    enabled=settings.sentence_merge_enabled,
)
minutes_gen = MinutesGenerator(translator)

# Per-client SSE broadcast queues
_sse_clients: list[asyncio.Queue] = []


def _add_sse_client() -> asyncio.Queue:
    """Register a new SSE client and return its queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=256)
    _sse_clients.append(q)
    logger.info(f"SSE client connected (total: {len(_sse_clients)})")
    return q


def _remove_sse_client(q: asyncio.Queue) -> None:
    """Unregister an SSE client."""
    try:
        _sse_clients.remove(q)
    except ValueError:
        pass
    logger.info(f"SSE client disconnected (total: {len(_sse_clients)})")


def _broadcast_to_sse(data: dict) -> None:
    """Send data to all connected SSE clients (non-blocking, drops if full)."""
    for q in _sse_clients:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            # Drop oldest message to make room for the new one
            try:
                q.get_nowait()
                q.put_nowait(data)
            except Exception:
                pass


class _TranslationBatcher:
    """Accumulate text and translate in a single API call after a delay."""

    def __init__(self, delay_secs: float = 8.0):
        self._delay = delay_secs
        self._pending: list[tuple[str, str, int]] = []  # (text, lang, timestamp)
        self._timer: asyncio.Task | None = None

    def add(self, text: str, language: str, timestamp: int) -> None:
        self._pending.append((text, language, timestamp))
        # Reset the timer on each new chunk
        if self._timer and not self._timer.done():
            self._timer.cancel()
        self._timer = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self) -> None:
        await asyncio.sleep(self._delay)
        await self.flush()

    async def flush(self) -> None:
        if not self._pending:
            return
        items = self._pending.copy()
        self._pending.clear()
        if self._timer and not self._timer.done():
            self._timer.cancel()
            self._timer = None

        combined_text = " ".join(text for text, _, _ in items)
        language = items[0][1]
        first_ts = items[0][2]

        logger.info(
            f"[TRANSLATE] Batch: {len(items)} chunks, {len(combined_text)} chars in 1 API call"
        )

        try:
            translated = await translator.translate(
                combined_text, language, settings.target_language
            )
            if translated != combined_text:
                update = TranslatedChunk(
                    original_text=combined_text,
                    translated_text=translated,
                    source_language=language,
                    target_language=settings.target_language,
                    timestamp=first_ts,
                    is_final=True,
                )
                _broadcast_to_sse(update.model_dump())
        except Exception as e:
            logger.error(f"Batch translation error: {e}")


_translation_batcher = _TranslationBatcher(delay_secs=settings.translation_batch_delay_secs)


async def _emit_final_chunk(chunk: TranslatedChunk) -> None:
    """Broadcast a ready final chunk to SSE, buffer in session, and queue translation."""
    _broadcast_to_sse(chunk.model_dump())

    if session_mgr.is_active:
        await session_mgr.add_chunk(chunk)

    if (
        settings.translation_mode != "disabled"
        and chunk.source_language != settings.target_language
    ):
        _translation_batcher.add(
            chunk.original_text, chunk.source_language, chunk.timestamp
        )


async def _process_transcripts() -> None:
    """Background task: receive from Rust WS, merge sentences, translate, broadcast."""

    listener_queue = ws_client.add_listener()
    logger.info("Transcript processor started, waiting for chunks...")

    while True:
        # Use a short timeout so we can periodically check the sentence merger
        try:
            raw_chunk = await asyncio.wait_for(listener_queue.get(), timeout=0.5)
        except asyncio.TimeoutError:
            # No data — check if the sentence merger needs to flush
            flushed = sentence_merger.check_timeout()
            if flushed:
                logger.info(f"[PIPELINE] Merger timeout flush: '{flushed.original_text[:60]}...'")
                await _emit_final_chunk(flushed)
            continue
        except asyncio.CancelledError:
            # Flush merger before exiting
            flushed = sentence_merger.flush()
            if flushed:
                await _emit_final_chunk(flushed)
            break

        chunk_type = raw_chunk.get("type", "")
        if chunk_type != "transcript":
            logger.debug(f"[PIPELINE] Non-transcript: type={chunk_type}")
            _broadcast_to_sse(raw_chunk)
            continue

        text = raw_chunk.get("text", "")
        language = raw_chunk.get("language", "auto")
        timestamp = raw_chunk.get("timestamp", 0)
        is_final = raw_chunk.get("is_final", False)

        if not text.strip():
            continue

        logger.info(f"[PIPELINE] Received: '{text[:80]}...' final={is_final} clients={len(_sse_clients)}")

        translated_chunk = TranslatedChunk(
            original_text=text,
            translated_text=text,  # original for now
            source_language=language,
            target_language=settings.target_language,
            timestamp=timestamp,
            is_final=is_final,
        )

        if not is_final:
            # Partial chunks → broadcast immediately (no delay)
            _broadcast_to_sse(translated_chunk.model_dump())
        else:
            # Final chunks → pass through sentence merger
            ready = sentence_merger.push(translated_chunk)
            if ready:
                await _emit_final_chunk(ready)


# --- Application lifecycle ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("Starting VoxVault Python Orchestrator")

    # Initialize SQLite database
    db_path = str(settings.db_path.expanduser())
    await init_db(db_path)

    # Ensure sessions directory exists
    sessions_dir = settings.sessions_dir.expanduser()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Connect to Rust WebSocket (non-blocking — retries in background)
    await ws_client.start()

    # Start transcript processing loop
    process_task = asyncio.create_task(_process_transcripts())

    yield

    # Shutdown
    logger.info("Shutting down VoxVault")
    process_task.cancel()
    try:
        await process_task
    except asyncio.CancelledError:
        pass
    await ws_client.stop()


# --- FastAPI app ---

app = FastAPI(
    title="VoxVault Orchestrator",
    description="Python orchestration layer for VoxVault real-time meeting transcription",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*", "tauri://localhost", "https://tauri.localhost"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- SSE Endpoint ---


@app.get("/api/transcript/stream")
async def stream_transcript():
    """Server-Sent Events endpoint for live transcript streaming."""

    client_queue = _add_sse_client()

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(client_queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            _remove_sse_client(client_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Session Endpoints ---


@app.post("/api/session/start", response_model=SessionInfo)
async def start_session(request: SessionStartRequest):
    """Start a new recording session."""
    session = await session_mgr.start_session(
        title=request.title,
        participants=request.participants,
    )
    return session


@app.post("/api/session/stop", response_model=SessionStopResponse)
async def stop_session():
    """Stop the current session and return summary."""
    if not session_mgr.is_active:
        raise HTTPException(status_code=400, detail="No active session")

    # Flush any pending sentence in the merger before ending the session
    flushed = sentence_merger.flush()
    if flushed:
        logger.info(f"[SESSION] Flushing merger on stop: '{flushed.original_text[:60]}...'")
        await _emit_final_chunk(flushed)

    # Flush any pending translation batch
    await _translation_batcher.flush()

    # Reset Apple FM sessions between meetings (free accumulated context)
    if settings.translation_mode == "apple" and hasattr(translator, "reset_session"):
        translator.reset_session()
        logger.info("[SESSION] Apple provider sessions reset")

    session_info, transcript = await session_mgr.end_session()
    if not session_info:
        raise HTTPException(status_code=500, detail="Failed to end session")

    duration = 0
    if session_info.started_at:
        from datetime import datetime
        duration = int((datetime.utcnow() - session_info.started_at).total_seconds())

    return SessionStopResponse(
        session_id=session_info.id,
        duration_seconds=duration,
        transcript_chunks=session_mgr.get_chunk_count(),
    )


@app.get("/api/session/current")
async def get_current_session():
    """Get info about the current active session."""
    if not session_mgr.is_active:
        return {"active": False}
    return {"active": True, "session": session_mgr.current_session}


# --- Minutes Endpoints ---


@app.post("/api/minutes/generate", response_model=MinutesResponse)
async def generate_minutes(request: MinutesRequest):
    """Generate meeting minutes for the last ended session."""
    # Get the transcript from the session manager's buffer
    # (this works right after stopping a session, before the buffer is cleared)
    if session_mgr.is_active:
        raise HTTPException(status_code=400, detail="Stop the session before generating minutes")

    transcript = session_mgr.get_full_transcript()
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="No transcript available")

    # Use the last session info or request data
    title = request.title or "Meeting"
    participants = request.participants

    from datetime import datetime
    content = await minutes_gen.generate(
        transcript=transcript,
        title=title,
        participants=participants,
        started_at=datetime.utcnow(),
        duration_seconds=0,
        language=settings.target_language,
    )

    sessions_dir = settings.sessions_dir.expanduser()
    file_path = await minutes_gen.save_minutes(content, "manual", sessions_dir)

    return MinutesResponse(
        session_id="manual",
        content=content,
        file_path=str(file_path),
    )


# --- Settings Endpoints ---


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current application settings."""
    return SettingsResponse(
        translation_mode=settings.translation_mode,
        target_language=settings.target_language,
        anthropic_api_key_set=bool(settings.anthropic_api_key),
        openai_api_key_set=bool(settings.openai_api_key),
        openrouter_api_key_set=bool(settings.openrouter_api_key),
        openrouter_model=settings.openrouter_model,
        sessions_dir=str(settings.sessions_dir),
        rust_ws_url=settings.rust_ws_url,
    )


@app.put("/api/settings")
async def update_settings(request: SettingsUpdateRequest):
    """Update application settings (runtime only, does not persist to .env)."""
    global translator, minutes_gen

    if request.translation_mode is not None:
        settings.translation_mode = request.translation_mode
    if request.target_language is not None:
        settings.target_language = request.target_language
    if request.anthropic_api_key is not None:
        settings.anthropic_api_key = request.anthropic_api_key
    if request.openai_api_key is not None:
        settings.openai_api_key = request.openai_api_key
    if request.openrouter_api_key is not None:
        settings.openrouter_api_key = request.openrouter_api_key
    if request.openrouter_model is not None:
        settings.openrouter_model = request.openrouter_model
    if request.sessions_dir is not None:
        settings.sessions_dir = Path(request.sessions_dir)

    # Recreate translation service with new settings
    translator = create_translation_service(
        mode=settings.translation_mode,
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        openrouter_api_key=settings.openrouter_api_key,
        openrouter_model=settings.openrouter_model,
        gemma_model_path=settings.gemma_model_path,
    )
    minutes_gen = MinutesGenerator(translator)

    return {"status": "ok", "message": "Settings updated"}


# --- Health ---


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    data = {
        "status": "ok",
        "rust_connected": ws_client.is_connected,
        "session_active": session_mgr.is_active,
        "translation_mode": settings.translation_mode,
    }
    if settings.translation_mode == "apple" and hasattr(translator, "is_available"):
        data["apple_fm_available"] = translator.is_available
    return data


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )

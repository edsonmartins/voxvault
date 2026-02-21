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
    gemma_model_path=settings.gemma_model_path,
)
session_mgr = SessionManager()
minutes_gen = MinutesGenerator(translator)

# Queue for SSE broadcast (translated chunks)
_sse_broadcast_queue: asyncio.Queue | None = None


async def _process_transcripts() -> None:
    """Background task: receive from Rust WS, translate, buffer, broadcast to SSE."""
    global _sse_broadcast_queue

    listener_queue = ws_client.add_listener()

    while True:
        try:
            raw_chunk = await listener_queue.get()
        except asyncio.CancelledError:
            break

        chunk_type = raw_chunk.get("type", "")
        if chunk_type != "transcript":
            # Forward status/error as-is to SSE
            if _sse_broadcast_queue:
                await _sse_broadcast_queue.put(raw_chunk)
            continue

        text = raw_chunk.get("text", "")
        language = raw_chunk.get("language", "auto")
        timestamp = raw_chunk.get("timestamp", 0)
        is_final = raw_chunk.get("is_final", False)

        if not text.strip():
            continue

        # Translate if enabled and is_final
        translated_text = text
        if is_final and settings.translation_mode != "disabled":
            translated_text = await translator.translate(
                text, language, settings.target_language
            )

        translated_chunk = TranslatedChunk(
            original_text=text,
            translated_text=translated_text,
            source_language=language,
            target_language=settings.target_language,
            timestamp=timestamp,
            is_final=is_final,
        )

        # Buffer in session
        if session_mgr.is_active:
            await session_mgr.add_chunk(translated_chunk)

        # Broadcast to SSE listeners
        if _sse_broadcast_queue:
            await _sse_broadcast_queue.put(translated_chunk.model_dump())


# --- Application lifecycle ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    global _sse_broadcast_queue

    logger.info("Starting VoxVault Python Orchestrator")

    # Initialize SQLite database
    db_path = str(settings.db_path.expanduser())
    await init_db(db_path)

    # Ensure sessions directory exists
    sessions_dir = settings.sessions_dir.expanduser()
    sessions_dir.mkdir(parents=True, exist_ok=True)

    # Create SSE broadcast queue
    _sse_broadcast_queue = asyncio.Queue(maxsize=512)

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

    async def event_generator():
        if _sse_broadcast_queue is None:
            return

        while True:
            try:
                data = await asyncio.wait_for(_sse_broadcast_queue.get(), timeout=30.0)
                yield f"data: {json.dumps(data)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive comment
                yield ": keepalive\n\n"
            except asyncio.CancelledError:
                break

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
    if request.sessions_dir is not None:
        settings.sessions_dir = Path(request.sessions_dir)

    # Recreate translation service with new settings
    translator = create_translation_service(
        mode=settings.translation_mode,
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        gemma_model_path=settings.gemma_model_path,
    )
    minutes_gen = MinutesGenerator(translator)

    return {"status": "ok", "message": "Settings updated"}


# --- Health ---


@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "rust_connected": ws_client.is_connected,
        "session_active": session_mgr.is_active,
        "translation_mode": settings.translation_mode,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=True,
    )

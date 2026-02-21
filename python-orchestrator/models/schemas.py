"""Pydantic models for VoxVault API and WebSocket messages."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- WebSocket messages from Rust ---


class TranscriptChunk(BaseModel):
    """Message received from Rust WebSocket server."""

    type: str  # "transcript" | "status" | "error"
    text: str
    language: str = ""
    timestamp: int = 0
    is_final: bool = False


# --- Internal models ---


class TranslatedChunk(BaseModel):
    """Transcript chunk after translation processing."""

    original_text: str
    translated_text: str
    source_language: str
    target_language: str
    timestamp: int
    is_final: bool = True


# --- API request/response models ---


class SessionStartRequest(BaseModel):
    """Request to start a new session."""

    title: str = ""
    participants: list[str] = Field(default_factory=list)


class SessionInfo(BaseModel):
    """Current session information."""

    id: str
    title: str
    started_at: datetime
    participants: list[str] = Field(default_factory=list)
    is_active: bool = True


class SessionStopResponse(BaseModel):
    """Response after stopping a session."""

    session_id: str
    duration_seconds: int
    minutes_path: str | None = None
    transcript_chunks: int = 0


class MinutesRequest(BaseModel):
    """Request to generate meeting minutes."""

    title: str = ""
    participants: list[str] = Field(default_factory=list)


class MinutesResponse(BaseModel):
    """Response with generated minutes."""

    session_id: str
    content: str
    file_path: str


class SettingsResponse(BaseModel):
    """Current application settings."""

    translation_mode: str
    target_language: str
    anthropic_api_key_set: bool
    openai_api_key_set: bool
    openrouter_api_key_set: bool
    openrouter_model: str
    sessions_dir: str
    rust_ws_url: str


class SettingsUpdateRequest(BaseModel):
    """Request to update settings."""

    translation_mode: str | None = None
    target_language: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    openrouter_model: str | None = None
    sessions_dir: str | None = None

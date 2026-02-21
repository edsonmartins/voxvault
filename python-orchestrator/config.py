"""VoxVault configuration via pydantic-settings."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_prefix="VOXVAULT_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Rust WebSocket bridge
    rust_ws_url: str = "ws://localhost:8765"

    # FastAPI server
    api_host: str = "127.0.0.1"
    api_port: int = 8766

    # Translation
    translation_mode: Literal["disabled", "claude", "openai", "local"] = "disabled"
    target_language: str = "pt"
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Local model (optional, for mode=local)
    gemma_model_path: str = ""

    # Storage
    sessions_dir: Path = Path.home() / "Documents" / "VoxVault" / "sessions"
    db_path: Path = Path.home() / "Documents" / "VoxVault" / "voxvault.db"


settings = Settings()

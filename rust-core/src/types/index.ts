/** A translated transcript chunk received via SSE from the Python orchestrator. */
export interface TranslatedChunk {
  original_text: string;
  translated_text: string;
  source_language: string;
  target_language: string;
  timestamp: number;
  is_final: boolean;
}

/** A status or error message from the Rust core (forwarded via Python SSE). */
export interface StatusMessage {
  type: "status" | "error";
  text: string;
  language?: string;
  timestamp: number;
  is_final: boolean;
}

/** Union of possible SSE event payloads. */
export type SSEEvent = TranslatedChunk | StatusMessage;

/** Session info returned by the Python API. */
export interface SessionInfo {
  id: string;
  title: string;
  started_at: string;
  participants: string[];
  is_active: boolean;
}

/** Response from stopping a session. */
export interface SessionStopResponse {
  session_id: string;
  duration_seconds: number;
  transcript_chunks: number;
}

/** Health check response. */
export interface HealthStatus {
  status: string;
  rust_connected: boolean;
  session_active: boolean;
  translation_mode: string;
}

/** Application settings from the Python API. */
export interface AppSettings {
  translation_mode: string;
  target_language: string;
  anthropic_api_key_set: boolean;
  openai_api_key_set: boolean;
  openrouter_api_key_set: boolean;
  openrouter_model: string;
  sessions_dir: string;
  rust_ws_url: string;
}

export function isTranslatedChunk(event: SSEEvent): event is TranslatedChunk {
  return "original_text" in event;
}

export function isStatusMessage(event: SSEEvent): event is StatusMessage {
  return "type" in event && (event as StatusMessage).type !== undefined;
}

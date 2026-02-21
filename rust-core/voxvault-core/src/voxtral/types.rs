use serde::Serialize;

/// Result of a transcription operation.
#[derive(Debug, Clone, Serialize)]
pub struct TranscriptResult {
    /// The transcribed text.
    pub text: String,
    /// Detected language code (e.g., "pt", "en", "es").
    pub language: String,
    /// Timestamp in milliseconds since epoch.
    pub timestamp_ms: u64,
    /// Whether this is a final (complete) chunk or partial.
    pub is_final: bool,
}

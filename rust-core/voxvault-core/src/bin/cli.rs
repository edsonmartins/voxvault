use anyhow::{Context, Result};
use clap::Parser;
use std::path::PathBuf;
use tokio::sync::mpsc;
use tracing::info;

use voxvault_core::audio::capture::AudioCapture;
use voxvault_core::audio::processor::AudioProcessor;
use voxvault_core::server::websocket::{TranscriptMessage, TranscriptServer};
use voxvault_core::voxtral::engine::VoxtralEngine;

#[derive(Parser)]
#[command(name = "voxvault-cli")]
#[command(about = "VoxVault CLI — real-time audio transcription via Voxtral")]
struct Cli {
    /// List available audio input devices and exit.
    #[arg(long)]
    list_devices: bool,

    /// Audio input device name (e.g., "VoxtralMeet Input").
    #[arg(short, long, default_value = "VoxtralMeet Input")]
    device: String,

    /// Path to the Voxtral Q4 GGUF model file.
    #[arg(long, default_value = "../../models/voxtral-q4.gguf")]
    model_path: String,

    /// Path to the tekken.json tokenizer file.
    #[arg(long, default_value = "../../models/tekken.json")]
    tokenizer_path: String,

    /// WebSocket server port.
    #[arg(long, default_value_t = 8765)]
    ws_port: u16,

    /// Audio buffer duration in milliseconds before sending to processor.
    #[arg(long, default_value_t = 500)]
    buffer_ms: u32,

    /// Minimum audio duration (seconds) before transcribing.
    #[arg(long, default_value_t = 3.0)]
    min_duration: f32,

    /// Maximum audio duration (seconds) to accumulate before transcribing.
    #[arg(long, default_value_t = 30.0)]
    max_duration: f32,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt()
        .with_target(false)
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "info".into()),
        )
        .init();

    let cli = Cli::parse();

    // List devices mode
    if cli.list_devices {
        let devices = AudioCapture::list_devices()?;
        println!("Available audio input devices:");
        for (i, name) in devices.iter().enumerate() {
            println!("  [{}] {}", i, name);
        }
        return Ok(());
    }

    // Start WebSocket server
    let server = TranscriptServer::new(cli.ws_port);
    let ws_sender = server.sender();

    let ws_handle = tokio::spawn(async move {
        if let Err(e) = server.run().await {
            tracing::error!("WebSocket server error: {}", e);
        }
    });

    info!(port = cli.ws_port, "WebSocket server started");

    // Load Voxtral engine
    let mut engine = VoxtralEngine::new(
        PathBuf::from(&cli.model_path),
        PathBuf::from(&cli.tokenizer_path),
    );

    info!("Loading Voxtral model (this may take 3-5 seconds)...");
    let _ = ws_sender.send(TranscriptMessage::status(
        "Loading model...".to_string(),
    ));
    let load_ms = engine.load().context("Failed to load Voxtral model")?;
    info!(load_ms, "Model loaded");
    let _ = ws_sender.send(TranscriptMessage::status("Ready".to_string()));

    // Set up audio capture pipeline
    let (audio_tx, mut audio_rx) = mpsc::channel(32);
    let mut capture =
        AudioCapture::new(&cli.device, cli.buffer_ms, audio_tx)
            .context("Failed to initialize audio capture")?;

    capture
        .start(cli.buffer_ms)
        .context("Failed to start audio capture")?;

    info!(device = cli.device, "Audio capture started. Press Ctrl+C to stop.");

    // Processing loop
    let mut processor = AudioProcessor::new(cli.min_duration, cli.max_duration);

    let process_handle = tokio::spawn(async move {
        while let Some(chunk) = audio_rx.recv().await {
            // Feed chunk to processor
            if let Some(audio_buffer) = processor.feed(chunk) {
                let partial_sender = ws_sender.clone();
                let partial_ts = chrono::Utc::now().timestamp_millis() as u64;

                // Transcribe with per-token streaming
                match engine.transcribe_streaming(audio_buffer, |partial_text: &str| {
                    // Send each partial token immediately via WebSocket
                    let msg = TranscriptMessage::transcript(
                        partial_text.to_string(),
                        "auto".to_string(),
                        partial_ts,
                        false, // is_final = false for partials
                    );
                    let _ = partial_sender.send(msg);
                }) {
                    Ok(result) => {
                        if !result.text.is_empty() {
                            println!("[{}] {}", result.language, result.text);

                            // Send final complete text
                            let msg = TranscriptMessage::transcript(
                                result.text,
                                result.language,
                                result.timestamp_ms,
                                true, // is_final = true
                            );
                            let _ = ws_sender.send(msg);
                        }
                    }
                    Err(e) => {
                        tracing::error!("Transcription error: {}", e);
                        let _ = ws_sender.send(TranscriptMessage::error(e.to_string()));
                    }
                }
            }
        }
    });

    // Wait for Ctrl+C
    tokio::signal::ctrl_c()
        .await
        .context("Failed to listen for ctrl+c")?;

    info!("Shutting down...");
    capture.stop();

    // Process any remaining audio
    // (processor.flush() would be called here in a full implementation)

    // Cancel tasks
    process_handle.abort();
    ws_handle.abort();

    info!("VoxVault CLI shut down cleanly.");
    Ok(())
}

use anyhow::{bail, Context, Result};
use burn::backend::wgpu::WgpuDevice;
use burn::backend::Wgpu;
use burn::tensor::{Tensor, TensorData};
use std::path::PathBuf;
use std::time::Instant;
use tracing::info;

use voxtral_mini_realtime::audio::{
    chunk::{chunk_audio, needs_chunking, ChunkConfig},
    mel::{MelConfig, MelSpectrogram},
    pad::{pad_audio, PadConfig},
    AudioBuffer,
};
use voxtral_mini_realtime::gguf::loader::Q4ModelLoader;
use voxtral_mini_realtime::gguf::model::Q4VoxtralModel;
use voxtral_mini_realtime::models::time_embedding::TimeEmbedding;
use voxtral_mini_realtime::tokenizer::VoxtralTokenizer;

use super::types::TranscriptResult;

type Backend = Wgpu;

/// Voxtral inference engine with lazy loading support (ADR-007).
///
/// The model is loaded into GPU memory only when `load()` is called
/// and freed when `unload()` is called, minimizing idle memory usage.
pub struct VoxtralEngine {
    model_path: PathBuf,
    tokenizer_path: PathBuf,
    device: WgpuDevice,
    // Loaded state (None when idle)
    model: Option<Q4VoxtralModel>,
    tokenizer: Option<VoxtralTokenizer>,
    mel_extractor: Option<MelSpectrogram>,
    t_embed: Option<Tensor<Backend, 3>>,
    /// Delay in tokens (1 token = 80ms). Default 6 = 480ms latency.
    delay: usize,
    /// Max mel frames per chunk (for GPU memory limits).
    max_mel_frames: usize,
}

impl VoxtralEngine {
    /// Create a new engine (does NOT load the model yet).
    pub fn new(model_path: PathBuf, tokenizer_path: PathBuf) -> Self {
        Self {
            model_path,
            tokenizer_path,
            device: WgpuDevice::default(),
            model: None,
            tokenizer: None,
            mel_extractor: None,
            t_embed: None,
            delay: 6,
            max_mel_frames: 1200,
        }
    }

    /// Check if the model is currently loaded.
    pub fn is_loaded(&self) -> bool {
        self.model.is_some()
    }

    /// Load the model into GPU memory. Returns load time in milliseconds.
    pub fn load(&mut self) -> Result<u64> {
        if self.is_loaded() {
            return Ok(0);
        }

        let start = Instant::now();

        // Load tokenizer
        info!(path = %self.tokenizer_path.display(), "Loading tokenizer");
        let tokenizer = VoxtralTokenizer::from_file(&self.tokenizer_path)
            .context("Failed to load tokenizer")?;

        // Load Q4 GGUF model
        info!(path = %self.model_path.display(), "Loading Q4 GGUF model");
        let mut loader = Q4ModelLoader::from_file(&self.model_path)
            .context("Failed to open GGUF file")?;
        let model = loader
            .load(&self.device)
            .context("Failed to load Q4 model")?;

        // Initialize mel extractor and time embedding
        let mel_extractor = MelSpectrogram::new(MelConfig::voxtral());
        let time_embed = TimeEmbedding::new(3072);
        let t_embed = time_embed.embed::<Backend>(self.delay as f32, &self.device);

        let elapsed_ms = start.elapsed().as_millis() as u64;

        self.model = Some(model);
        self.tokenizer = Some(tokenizer);
        self.mel_extractor = Some(mel_extractor);
        self.t_embed = Some(t_embed);

        info!(elapsed_ms, "VoxtralEngine loaded");
        Ok(elapsed_ms)
    }

    /// Unload the model from GPU memory.
    pub fn unload(&mut self) {
        self.model = None;
        self.tokenizer = None;
        self.mel_extractor = None;
        self.t_embed = None;
        info!("VoxtralEngine unloaded");
    }

    /// Transcribe an audio buffer. The model must be loaded first.
    pub fn transcribe(&self, audio: AudioBuffer) -> Result<TranscriptResult> {
        let model = self.model.as_ref().context("Model not loaded")?;
        let tokenizer = self.tokenizer.as_ref().context("Tokenizer not loaded")?;
        let mel_extractor = self.mel_extractor.as_ref().context("Mel extractor not loaded")?;
        let t_embed = self.t_embed.as_ref().context("Time embedding not loaded")?;

        let pad_config = PadConfig::voxtral();
        let chunk_config = ChunkConfig::voxtral().with_max_frames(self.max_mel_frames);

        let timestamp_ms = chrono::Utc::now().timestamp_millis() as u64;

        // Check if audio needs chunking (for long segments)
        let chunks = if needs_chunking(audio.samples.len(), &chunk_config) {
            let chunks = chunk_audio(&audio.samples, &chunk_config);
            info!(
                total_chunks = chunks.len(),
                "Audio exceeds chunk limit; transcribing in chunks"
            );
            chunks
        } else {
            vec![voxtral_mini_realtime::audio::AudioChunk {
                samples: audio.samples.clone(),
                start_sample: 0,
                end_sample: audio.samples.len(),
                index: 0,
                is_last: true,
            }]
        };

        let mut texts = Vec::new();

        for chunk in &chunks {
            let chunk_audio = AudioBuffer::new(chunk.samples.clone(), audio.sample_rate);
            let mel_tensor = self.compute_mel(&chunk_audio, mel_extractor, &pad_config)?;

            // Run Q4 streaming inference
            let generated = model.transcribe_streaming(mel_tensor, t_embed.clone());

            // Decode tokens, filtering control tokens (< 1000)
            let text = self.decode_tokens(tokenizer, &generated)?;
            if !text.trim().is_empty() {
                texts.push(text.trim().to_string());
            }
        }

        let full_text = texts.join(" ");

        Ok(TranscriptResult {
            text: full_text,
            language: "auto".to_string(), // Voxtral auto-detects language
            timestamp_ms,
            is_final: true,
        })
    }

    /// Compute mel spectrogram tensor from audio buffer.
    fn compute_mel(
        &self,
        audio: &AudioBuffer,
        mel_extractor: &MelSpectrogram,
        pad_config: &PadConfig,
    ) -> Result<Tensor<Backend, 3>> {
        let padded = pad_audio(audio, pad_config);
        let mel = mel_extractor.compute_log(&padded.samples);
        let n_frames = mel.len();
        let n_mels = if n_frames > 0 { mel[0].len() } else { 0 };

        if n_frames == 0 {
            bail!("Audio too short to produce mel frames");
        }

        // Transpose from [frames, mels] to [mels, frames]
        let mut mel_transposed = vec![vec![0.0f32; n_frames]; n_mels];
        for (frame_idx, frame) in mel.iter().enumerate() {
            for (mel_idx, &val) in frame.iter().enumerate() {
                mel_transposed[mel_idx][frame_idx] = val;
            }
        }
        let mel_flat: Vec<f32> = mel_transposed.into_iter().flatten().collect();

        Ok(Tensor::from_data(
            TensorData::new(mel_flat, [1, n_mels, n_frames]),
            &self.device,
        ))
    }

    /// Filter control tokens and decode to text.
    fn decode_tokens(&self, tokenizer: &VoxtralTokenizer, generated: &[i32]) -> Result<String> {
        let text_tokens: Vec<u32> = generated
            .iter()
            .filter(|&&t| t >= 1000)
            .map(|&t| t as u32)
            .collect();
        tokenizer
            .decode(&text_tokens)
            .context("Failed to decode tokens")
    }

    /// Transcribe an audio buffer with per-token streaming callback.
    ///
    /// Calls `on_partial(text_so_far)` each time a new text token is decoded,
    /// providing the accumulated transcription. The final complete text is
    /// returned in the `TranscriptResult` with `is_final: true`.
    pub fn transcribe_streaming<F: FnMut(&str)>(
        &self,
        audio: AudioBuffer,
        on_partial: F,
    ) -> Result<TranscriptResult> {
        let model = self.model.as_ref().context("Model not loaded")?;
        let tokenizer = self.tokenizer.as_ref().context("Tokenizer not loaded")?;
        let mel_extractor = self.mel_extractor.as_ref().context("Mel extractor not loaded")?;
        let t_embed = self.t_embed.as_ref().context("Time embedding not loaded")?;

        let streamer = super::streaming::StreamingTranscriber::new(
            model,
            tokenizer,
            mel_extractor,
            t_embed,
            &self.device,
            self.max_mel_frames,
        );

        streamer.transcribe(audio, on_partial)
    }
}

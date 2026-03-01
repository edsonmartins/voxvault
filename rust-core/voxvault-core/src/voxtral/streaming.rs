//! Streaming transcription with per-token callback.
//!
//! Reimplements the autoregressive decode loop from `Q4VoxtralModel::transcribe_streaming()`
//! externally, using the model's public decoder API. This allows injecting a callback
//! after each token is generated, enabling real-time text streaming to WebSocket clients.

use anyhow::{bail, Context, Result};
use burn::backend::wgpu::WgpuDevice;
use burn::backend::Wgpu;
use burn::prelude::ElementConversion;
use burn::tensor::{Tensor, TensorData};
use tracing::info;

use voxtral_mini_realtime::audio::{
    chunk::{chunk_audio, needs_chunking, ChunkConfig},
    mel::MelSpectrogram,
    pad::{pad_audio, PadConfig},
    AudioBuffer,
};
use voxtral_mini_realtime::gguf::model::Q4VoxtralModel;
use voxtral_mini_realtime::tokenizer::VoxtralTokenizer;

use super::types::TranscriptResult;

type Backend = Wgpu;

const PREFIX_LEN: usize = 38;
const BOS_TOKEN: i32 = 1;
const STREAMING_PAD: i32 = 32;
const TEXT_TOKEN_OFFSET: i32 = 1000;

/// Streaming transcriber that yields tokens one-by-one via callback.
///
/// Uses the Q4 model's public decoder API to run the autoregressive decode loop,
/// calling a user-provided callback each time a new text token extends the
/// transcription.
pub struct StreamingTranscriber<'a> {
    model: &'a Q4VoxtralModel,
    tokenizer: &'a VoxtralTokenizer,
    mel_extractor: &'a MelSpectrogram,
    t_embed: &'a Tensor<Backend, 3>,
    device: &'a WgpuDevice,
    max_mel_frames: usize,
}

impl<'a> StreamingTranscriber<'a> {
    /// Create a new streaming transcriber.
    pub fn new(
        model: &'a Q4VoxtralModel,
        tokenizer: &'a VoxtralTokenizer,
        mel_extractor: &'a MelSpectrogram,
        t_embed: &'a Tensor<Backend, 3>,
        device: &'a WgpuDevice,
        max_mel_frames: usize,
    ) -> Self {
        Self {
            model,
            tokenizer,
            mel_extractor,
            t_embed,
            device,
            max_mel_frames,
        }
    }

    /// Transcribe audio with per-token streaming callback.
    ///
    /// Calls `on_partial(text_so_far)` each time a new text token is decoded,
    /// providing the accumulated transcription. Control tokens (< 1000) are
    /// filtered; the callback fires only when decoded text actually grows.
    ///
    /// Returns the final `TranscriptResult` with `is_final: true`.
    pub fn transcribe<F: FnMut(&str)>(
        &self,
        audio: AudioBuffer,
        mut on_partial: F,
    ) -> Result<TranscriptResult> {
        let start_time = std::time::Instant::now();
        let audio_duration_secs = audio.samples.len() as f64 / audio.sample_rate as f64;

        let pad_config = PadConfig::voxtral();
        let chunk_config = ChunkConfig::voxtral().with_max_frames(self.max_mel_frames);
        let timestamp_ms = chrono::Utc::now().timestamp_millis() as u64;

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
            let mel_tensor = self.compute_mel(&chunk_audio, &pad_config)?;

            let text = self.decode_streaming(mel_tensor, &mut on_partial)?;
            if !text.trim().is_empty() {
                texts.push(text.trim().to_string());
            }
        }

        let full_text = texts.join(" ");

        let elapsed_secs = start_time.elapsed().as_secs_f64();
        let rtf = if audio_duration_secs > 0.0 {
            Some(elapsed_secs / audio_duration_secs)
        } else {
            None
        };

        Ok(TranscriptResult {
            text: full_text,
            language: "auto".to_string(),
            timestamp_ms,
            is_final: true,
            rtf,
        })
    }

    /// Run the autoregressive decode loop with per-token callback.
    ///
    /// This reimplements `Q4VoxtralModel::transcribe_streaming()` (model.rs:873-963)
    /// using the model's public decoder API, adding callback invocations.
    fn decode_streaming<F: FnMut(&str)>(
        &self,
        mel: Tensor<Backend, 3>,
        on_partial: &mut F,
    ) -> Result<String> {
        let audio_embeds = self.model.encode_audio(mel);
        let [_, seq_len, d_model] = audio_embeds.dims();

        if seq_len < PREFIX_LEN {
            return Ok(String::new());
        }

        let decoder = self.model.decoder();

        // Build prefix: [BOS, PAD, PAD, ..., PAD] (38 tokens)
        let mut prefix: Vec<i32> = vec![BOS_TOKEN];
        prefix.extend(std::iter::repeat_n(STREAMING_PAD, PREFIX_LEN - 1));

        let prefix_text_embeds = decoder.embed_tokens_from_ids(&prefix, 1, PREFIX_LEN);

        let prefix_audio = audio_embeds
            .clone()
            .slice([0..1, 0..PREFIX_LEN, 0..d_model]);

        let prefix_inputs = prefix_audio + prefix_text_embeds;

        // Pre-allocate KV cache for the known sequence length
        let mut decoder_cache = self.model.create_decoder_cache_preallocated(seq_len);

        // Prefill: process all prefix positions at once
        let hidden = decoder.forward_hidden_with_cache(
            prefix_inputs,
            self.t_embed.clone(),
            &mut decoder_cache,
        );
        let logits = decoder.lm_head(hidden);

        // First token prediction from last prefix position
        let last_logits =
            logits
                .clone()
                .slice([0..1, (PREFIX_LEN - 1)..PREFIX_LEN, 0..logits.dims()[2]]);
        let first_pred = last_logits.argmax(2);
        let first_token: i32 = first_pred.into_scalar().elem();

        let mut generated = prefix;
        generated.push(first_token);

        // Track text tokens for incremental decoding
        let mut text_token_ids: Vec<u32> = Vec::new();
        let mut last_decoded_len: usize = 0;

        // Emit first token if it's text
        if first_token >= TEXT_TOKEN_OFFSET {
            text_token_ids.push(first_token as u32);
            if let Ok(decoded) = self.tokenizer.decode(&text_token_ids) {
                let trimmed = decoded.trim().to_string();
                if !trimmed.is_empty() {
                    last_decoded_len = trimmed.len();
                    on_partial(&trimmed);
                }
            }
        }

        // Pre-slice all audio positions to avoid cloning full tensor each step
        let audio_slices: Vec<Tensor<Backend, 3>> = (PREFIX_LEN..seq_len)
            .map(|pos| audio_embeds.clone().slice([0..1, pos..pos + 1, 0..d_model]))
            .collect();
        drop(audio_embeds);

        // Autoregressive decode loop — one token per iteration
        for pos in (PREFIX_LEN + 1)..seq_len {
            let new_token = generated[pos - 1];

            let text_embed = decoder.embed_tokens_from_ids(&[new_token], 1, 1);
            let audio_pos = audio_slices[pos - 1 - PREFIX_LEN].clone();
            let input = audio_pos + text_embed;

            let hidden = decoder.forward_hidden_with_cache(
                input,
                self.t_embed.clone(),
                &mut decoder_cache,
            );
            let logits = decoder.lm_head(hidden);

            let pred = logits.argmax(2);
            let next_token: i32 = pred.into_scalar().elem();

            generated.push(next_token);

            // Emit text tokens incrementally
            if next_token >= TEXT_TOKEN_OFFSET {
                text_token_ids.push(next_token as u32);
                if let Ok(decoded) = self.tokenizer.decode(&text_token_ids) {
                    let trimmed = decoded.trim().to_string();
                    if trimmed.len() > last_decoded_len {
                        last_decoded_len = trimmed.len();
                        on_partial(&trimmed);
                    }
                }
            }
        }

        // Decode final text from all generated tokens
        let final_tokens: Vec<i32> = generated.into_iter().skip(PREFIX_LEN).collect();
        let text_tokens: Vec<u32> = final_tokens
            .iter()
            .filter(|&&t| t >= TEXT_TOKEN_OFFSET)
            .map(|&t| t as u32)
            .collect();

        self.tokenizer
            .decode(&text_tokens)
            .context("Failed to decode tokens")
    }

    /// Compute mel spectrogram tensor from audio buffer.
    fn compute_mel(
        &self,
        audio: &AudioBuffer,
        pad_config: &PadConfig,
    ) -> Result<Tensor<Backend, 3>> {
        let padded = pad_audio(audio, pad_config);
        let mel = self.mel_extractor.compute_log(&padded.samples);
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
            self.device,
        ))
    }
}

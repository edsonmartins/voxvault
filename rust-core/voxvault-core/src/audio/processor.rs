use tracing::info;
use voxtral_mini_realtime::audio::{AudioBuffer, resample::resample_to_16k};

use super::capture::AudioChunk;

/// Processes raw audio chunks into AudioBuffers suitable for Voxtral inference.
///
/// Handles resampling to 16kHz (required by Voxtral) and accumulation
/// of multiple chunks into a larger window for batch transcription.
pub struct AudioProcessor {
    /// Target sample rate (always 16000 for Voxtral).
    target_sample_rate: u32,
    /// Accumulated samples at target sample rate.
    accumulated: Vec<f32>,
    /// Minimum number of samples before yielding a buffer for transcription.
    /// Default: 16000 * 5 = 80000 (5 seconds).
    min_samples: usize,
    /// Maximum number of samples to accumulate.
    /// Default: 16000 * 30 = 480000 (30 seconds).
    max_samples: usize,
}

impl AudioProcessor {
    /// Create a new processor.
    ///
    /// - `min_duration_secs`: minimum audio duration before yielding for transcription
    /// - `max_duration_secs`: maximum audio duration to accumulate
    pub fn new(min_duration_secs: f32, max_duration_secs: f32) -> Self {
        let target_sample_rate = 16000;
        Self {
            target_sample_rate,
            accumulated: Vec::new(),
            min_samples: (target_sample_rate as f32 * min_duration_secs) as usize,
            max_samples: (target_sample_rate as f32 * max_duration_secs) as usize,
        }
    }

    /// Feed a raw audio chunk. Returns an AudioBuffer if enough audio has accumulated.
    pub fn feed(&mut self, chunk: AudioChunk) -> Option<AudioBuffer> {
        let samples = if chunk.sample_rate != self.target_sample_rate {
            // Resample to 16kHz using voxtral's built-in resampler
            let buffer = AudioBuffer::new(chunk.samples, chunk.sample_rate);
            match resample_to_16k(&buffer) {
                Ok(resampled) => resampled.samples,
                Err(e) => {
                    tracing::error!("Resampling failed: {}", e);
                    return None;
                }
            }
        } else {
            chunk.samples
        };

        self.accumulated.extend_from_slice(&samples);

        // Yield when we have enough accumulated audio
        if self.accumulated.len() >= self.min_samples {
            Some(self.take_buffer())
        } else {
            None
        }
    }

    /// Force-flush any accumulated audio into a buffer (e.g., at session end).
    pub fn flush(&mut self) -> Option<AudioBuffer> {
        if self.accumulated.is_empty() {
            return None;
        }
        Some(self.take_buffer())
    }

    /// Take accumulated samples and create an AudioBuffer, applying peak normalization.
    fn take_buffer(&mut self) -> AudioBuffer {
        // Cap at max_samples to avoid excessive memory usage
        let take_len = self.accumulated.len().min(self.max_samples);
        let samples: Vec<f32> = self.accumulated.drain(..take_len).collect();

        let mut buffer = AudioBuffer::new(samples, self.target_sample_rate);
        // Critical for Q4 inference: quiet audio needs normalization
        buffer.peak_normalize(0.95);

        info!(
            samples = buffer.samples.len(),
            duration_secs = buffer.samples.len() as f32 / self.target_sample_rate as f32,
            "Audio buffer ready for transcription"
        );

        buffer
    }

    /// Reset the processor, discarding any accumulated audio.
    pub fn reset(&mut self) {
        self.accumulated.clear();
    }

    /// Get the number of currently accumulated samples.
    pub fn accumulated_samples(&self) -> usize {
        self.accumulated.len()
    }

    /// Get the accumulated duration in seconds.
    pub fn accumulated_duration_secs(&self) -> f32 {
        self.accumulated.len() as f32 / self.target_sample_rate as f32
    }
}

impl Default for AudioProcessor {
    fn default() -> Self {
        // 5 seconds minimum, 30 seconds maximum
        Self::new(5.0, 30.0)
    }
}

use tracing::info;
use voxtral_mini_realtime::audio::{AudioBuffer, resample::resample_to_16k};

use super::capture::AudioChunk;

/// Processes raw audio chunks into AudioBuffers suitable for Voxtral inference.
///
/// Includes Voice Activity Detection (VAD) to skip silence and dynamic
/// batching that yields at natural speech pauses instead of fixed intervals.
pub struct AudioProcessor {
    /// Target sample rate (always 16000 for Voxtral).
    target_sample_rate: u32,
    /// Accumulated samples at target sample rate.
    accumulated: Vec<f32>,
    /// Minimum number of samples before yielding a buffer for transcription.
    min_samples: usize,
    /// Maximum number of samples to accumulate.
    max_samples: usize,

    // --- VAD (Voice Activity Detection) ---
    /// RMS energy threshold below which audio is considered silence.
    speech_threshold: f32,
    /// Number of consecutive silent chunks observed.
    silence_count: usize,
    /// Number of silent chunks after speech before yielding (speech pause).
    /// With 500ms chunks, 2 = 1 second of silence triggers a yield.
    silence_pause_chunks: usize,
    /// Whether any speech was detected in the current accumulation.
    has_speech: bool,
    /// Pre-roll buffer: last silent chunk kept for context so we don't
    /// clip the beginning of speech.
    pre_roll: Vec<f32>,
}

impl AudioProcessor {
    /// Create a new processor.
    ///
    /// - `min_duration_secs`: minimum audio duration before yielding for transcription
    /// - `max_duration_secs`: maximum audio duration to accumulate
    /// - `silence_pause_ms`: milliseconds of silence before yielding (e.g. 1000 = 1s)
    /// - `buffer_ms`: audio buffer duration in ms (used to calculate silence chunk count)
    /// - `speech_threshold`: RMS energy threshold for speech detection (e.g. 0.005)
    pub fn new(
        min_duration_secs: f32,
        max_duration_secs: f32,
        silence_pause_ms: u32,
        buffer_ms: u32,
        speech_threshold: f32,
    ) -> Self {
        let target_sample_rate = 16000;
        let silence_pause_chunks = (silence_pause_ms / buffer_ms.max(1)) as usize;
        info!(
            silence_pause_ms,
            buffer_ms,
            silence_pause_chunks,
            speech_threshold,
            "AudioProcessor VAD config"
        );
        Self {
            target_sample_rate,
            accumulated: Vec::new(),
            min_samples: (target_sample_rate as f32 * min_duration_secs) as usize,
            max_samples: (target_sample_rate as f32 * max_duration_secs) as usize,
            speech_threshold,
            silence_count: 0,
            silence_pause_chunks,
            has_speech: false,
            pre_roll: Vec::new(),
        }
    }

    /// Calculate RMS (Root Mean Square) energy of audio samples.
    fn rms(samples: &[f32]) -> f32 {
        if samples.is_empty() {
            return 0.0;
        }
        let sum_sq: f32 = samples.iter().map(|&s| s * s).sum();
        (sum_sq / samples.len() as f32).sqrt()
    }

    /// Feed a raw audio chunk. Returns an AudioBuffer if enough speech
    /// audio has accumulated, or None if still waiting/silence.
    pub fn feed(&mut self, chunk: AudioChunk) -> Option<AudioBuffer> {
        let samples = if chunk.sample_rate != self.target_sample_rate {
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

        let energy = Self::rms(&samples);
        let is_speech = energy >= self.speech_threshold;

        if is_speech {
            // Speech detected
            if !self.has_speech && !self.pre_roll.is_empty() {
                // Prepend pre-roll so we don't clip the start of speech
                self.accumulated.extend_from_slice(&self.pre_roll);
                self.pre_roll.clear();
            }
            self.has_speech = true;
            self.silence_count = 0;
            self.accumulated.extend_from_slice(&samples);
        } else {
            // Silence
            self.silence_count += 1;

            if self.has_speech {
                // Still accumulating — include trailing silence for context
                self.accumulated.extend_from_slice(&samples);

                // Speech pause detected → yield what we have (natural break)
                if self.silence_count >= self.silence_pause_chunks
                    && self.accumulated.len() >= self.min_samples
                {
                    return Some(self.take_buffer());
                }
            } else {
                // Pure silence, no speech yet — just keep as pre-roll
                self.pre_roll = samples;
            }
        }

        // Hard limits: yield at max_samples regardless
        if self.accumulated.len() >= self.max_samples {
            return Some(self.take_buffer());
        }

        // Yield at min_samples if we have speech and silence pause
        if self.has_speech
            && self.accumulated.len() >= self.min_samples
            && self.silence_count >= self.silence_pause_chunks
        {
            return Some(self.take_buffer());
        }

        None
    }

    /// Force-flush any accumulated audio into a buffer (e.g., at session end).
    pub fn flush(&mut self) -> Option<AudioBuffer> {
        if self.accumulated.is_empty() || !self.has_speech {
            self.reset();
            return None;
        }
        Some(self.take_buffer())
    }

    /// Take accumulated samples and create an AudioBuffer, applying peak normalization.
    fn take_buffer(&mut self) -> AudioBuffer {
        // Cap at max_samples to avoid excessive memory usage
        let take_len = self.accumulated.len().min(self.max_samples);
        let samples: Vec<f32> = self.accumulated.drain(..take_len).collect();

        // Reset VAD state for next accumulation
        self.has_speech = false;
        self.silence_count = 0;
        self.pre_roll.clear();

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
        self.has_speech = false;
        self.silence_count = 0;
        self.pre_roll.clear();
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
        // 3s min, 30s max, 1000ms silence pause, 500ms buffer, 0.005 threshold
        Self::new(3.0, 30.0, 1000, 500, 0.005)
    }
}

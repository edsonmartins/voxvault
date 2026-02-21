use anyhow::{bail, Context, Result};
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Device, SampleFormat, Stream, StreamConfig};
use std::sync::Arc;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

/// Captured audio chunk with metadata.
pub struct AudioChunk {
    /// PCM samples as f32.
    pub samples: Vec<f32>,
    /// Sample rate of the captured audio.
    pub sample_rate: u32,
}

/// Real-time audio capture from a system audio device via cpal.
pub struct AudioCapture {
    device: Device,
    sample_rate: u32,
    sender: mpsc::Sender<AudioChunk>,
    stream: Option<Stream>,
}

impl AudioCapture {
    /// Create a new AudioCapture targeting the specified device name.
    ///
    /// `buffer_duration_ms` controls how often chunks are sent (e.g., 500ms).
    pub fn new(
        device_name: &str,
        buffer_duration_ms: u32,
        sender: mpsc::Sender<AudioChunk>,
    ) -> Result<Self> {
        let device = Self::find_device(device_name)?;

        let config = device
            .default_input_config()
            .context("Failed to get default input config")?;

        let sample_rate = config.sample_rate().0;
        info!(
            device = device_name,
            sample_rate,
            channels = config.channels(),
            format = ?config.sample_format(),
            "Audio device configured"
        );

        let _ = buffer_duration_ms; // used in start() for buffer sizing

        Ok(Self {
            device,
            sample_rate,
            sender,
            stream: None,
        })
    }

    /// List all available input audio devices.
    pub fn list_devices() -> Result<Vec<String>> {
        let host = cpal::default_host();
        let devices: Vec<String> = host
            .input_devices()
            .context("Failed to enumerate input devices")?
            .filter_map(|d| d.name().ok())
            .collect();
        Ok(devices)
    }

    /// Find a device by name.
    fn find_device(name: &str) -> Result<Device> {
        let host = cpal::default_host();
        let devices = host
            .input_devices()
            .context("Failed to enumerate input devices")?;

        for device in devices {
            if let Ok(device_name) = device.name() {
                if device_name == name {
                    return Ok(device);
                }
            }
        }

        bail!(
            "Audio device '{}' not found. Available devices: {:?}",
            name,
            Self::list_devices().unwrap_or_default()
        );
    }

    /// Start capturing audio. Chunks are sent through the mpsc channel.
    pub fn start(&mut self, buffer_duration_ms: u32) -> Result<()> {
        if self.stream.is_some() {
            bail!("Audio capture already running");
        }

        let config = self
            .device
            .default_input_config()
            .context("Failed to get input config")?;

        let sample_rate = config.sample_rate().0;
        let channels = config.channels() as usize;
        let sample_format = config.sample_format();

        // Calculate buffer size based on desired duration
        let buffer_size = (sample_rate as usize * buffer_duration_ms as usize) / 1000;

        let sender = self.sender.clone();
        let buffer = Arc::new(std::sync::Mutex::new(Vec::with_capacity(buffer_size)));
        let buffer_clone = Arc::clone(&buffer);

        let stream_config: StreamConfig = config.into();

        let err_fn = |err: cpal::StreamError| {
            error!("Audio stream error: {}", err);
        };

        let stream = match sample_format {
            SampleFormat::F32 => self.device.build_input_stream(
                &stream_config,
                move |data: &[f32], _: &cpal::InputCallbackInfo| {
                    process_samples(data, channels, &buffer_clone, buffer_size, &sender, sample_rate);
                },
                err_fn,
                None,
            ),
            SampleFormat::I16 => self.device.build_input_stream(
                &stream_config,
                move |data: &[i16], _: &cpal::InputCallbackInfo| {
                    let float_data: Vec<f32> =
                        data.iter().map(|&s| s as f32 / i16::MAX as f32).collect();
                    process_samples(
                        &float_data,
                        channels,
                        &buffer_clone,
                        buffer_size,
                        &sender,
                        sample_rate,
                    );
                },
                err_fn,
                None,
            ),
            SampleFormat::I32 => self.device.build_input_stream(
                &stream_config,
                move |data: &[i32], _: &cpal::InputCallbackInfo| {
                    let float_data: Vec<f32> =
                        data.iter().map(|&s| s as f32 / i32::MAX as f32).collect();
                    process_samples(
                        &float_data,
                        channels,
                        &buffer_clone,
                        buffer_size,
                        &sender,
                        sample_rate,
                    );
                },
                err_fn,
                None,
            ),
            format => {
                bail!("Unsupported sample format: {:?}", format);
            }
        }
        .context("Failed to build input stream")?;

        stream.play().context("Failed to start audio stream")?;
        self.stream = Some(stream);

        info!(
            buffer_duration_ms,
            buffer_size, "Audio capture started"
        );

        Ok(())
    }

    /// Stop capturing audio.
    pub fn stop(&mut self) {
        if let Some(stream) = self.stream.take() {
            drop(stream);
            info!("Audio capture stopped");
        }
    }

    /// Get the sample rate of the captured audio.
    pub fn sample_rate(&self) -> u32 {
        self.sample_rate
    }
}

/// Process incoming audio samples: downmix to mono, buffer, and send when full.
fn process_samples(
    data: &[f32],
    channels: usize,
    buffer: &Arc<std::sync::Mutex<Vec<f32>>>,
    buffer_size: usize,
    sender: &mpsc::Sender<AudioChunk>,
    sample_rate: u32,
) {
    // Downmix to mono by averaging channels
    let mono: Vec<f32> = if channels == 1 {
        data.to_vec()
    } else {
        data.chunks(channels)
            .map(|frame| frame.iter().sum::<f32>() / channels as f32)
            .collect()
    };

    let mut buf = buffer.lock().unwrap();
    buf.extend_from_slice(&mono);

    // Send chunks when buffer is full
    while buf.len() >= buffer_size {
        let chunk: Vec<f32> = buf.drain(..buffer_size).collect();
        let audio_chunk = AudioChunk {
            samples: chunk,
            sample_rate,
        };
        if sender.try_send(audio_chunk).is_err() {
            warn!("Audio chunk dropped: receiver not keeping up");
        }
    }
}

impl Drop for AudioCapture {
    fn drop(&mut self) {
        self.stop();
    }
}

//! Programmatic macOS audio device setup via CoreAudio.
//!
//! Creates Aggregate Devices on app startup and destroys them on shutdown:
//! - **VoxVault Capture**: BlackHole 2ch — captures system/meeting audio
//! - **VoxVault Mic**: BlackHole 16ch — virtual mic for TTS output to Zoom/Teams
//! - **VoxVault Output**: Multi-Output combining default output + BlackHole 2ch

#[cfg(target_os = "macos")]
mod macos {
    use core_foundation::base::TCFType;
    use core_foundation::boolean::CFBoolean;
    use core_foundation::string::CFString;
    use core_foundation_sys::runloop::{kCFRunLoopDefaultMode, CFRunLoopRunInMode};
    use coreaudio_sys::{
        kAudioHardwareNoError, kAudioHardwarePropertyDefaultOutputDevice,
        kAudioHardwarePropertyDevices, kAudioObjectPropertyElementMain,
        kAudioObjectPropertyScopeGlobal, kAudioObjectSystemObject, AudioDeviceID,
        AudioHardwareCreateAggregateDevice, AudioHardwareDestroyAggregateDevice,
        AudioObjectGetPropertyData, AudioObjectGetPropertyDataSize,
        AudioObjectPropertyAddress, AudioObjectSetPropertyData,
    };
    use std::ffi::c_void;
    use std::mem;
    use std::sync::Mutex;
    use tracing::{error, info, warn};

    // CoreAudio aggregate device dictionary keys
    const AGGREGATE_DEVICE_NAME_KEY: &str = "name";
    const AGGREGATE_DEVICE_UID_KEY: &str = "uid";
    const AGGREGATE_DEVICE_SUB_LIST_KEY: &str = "subdevices";
    const AGGREGATE_DEVICE_MASTER_KEY: &str = "master";
    const AGGREGATE_DEVICE_PRIVATE_KEY: &str = "private";

    // Sub-device dictionary keys
    const SUB_DEVICE_UID_KEY: &str = "uid";

    // VoxVault device configuration
    const VOXVAULT_CAPTURE_UID: &str = "com.voxvault.capture";
    const VOXVAULT_CAPTURE_NAME: &str = "VoxVault Capture";
    const VOXVAULT_MIC_UID: &str = "com.voxvault.mic";
    const VOXVAULT_MIC_NAME: &str = "VoxVault Mic";
    const VOXVAULT_OUTPUT_UID: &str = "com.voxvault.output";
    const VOXVAULT_OUTPUT_NAME: &str = "VoxVault Output";

    // BlackHole device name patterns
    const BLACKHOLE_2CH_NAME: &str = "BlackHole 2ch";
    const BLACKHOLE_16CH_NAME: &str = "BlackHole 16ch";

    /// Tracks device IDs created by this process so we can destroy them on shutdown.
    static CREATED_DEVICES: Mutex<Vec<AudioDeviceID>> = Mutex::new(Vec::new());

    /// Stores the original default output device ID to restore on teardown.
    static ORIGINAL_OUTPUT_DEVICE: Mutex<Option<AudioDeviceID>> = Mutex::new(None);

    #[derive(Debug, Clone, serde::Serialize)]
    pub struct AudioDeviceInfo {
        pub id: u32,
        pub uid: String,
        pub name: String,
    }

    #[derive(Debug, Clone, serde::Serialize)]
    pub struct SetupResult {
        pub capture_device: Option<String>,
        pub mic_device: Option<String>,
        pub multi_output_device: Option<String>,
        pub blackhole_2ch_found: bool,
        pub blackhole_16ch_found: bool,
        pub errors: Vec<String>,
    }

    #[derive(Debug, Clone, serde::Serialize)]
    pub struct TeardownResult {
        pub devices_destroyed: usize,
        pub errors: Vec<String>,
    }

    /// Get the UID of an audio device by its ID.
    fn get_device_uid(device_id: AudioDeviceID) -> Option<String> {
        use coreaudio_sys::kAudioDevicePropertyDeviceUID;
        let address = AudioObjectPropertyAddress {
            mSelector: kAudioDevicePropertyDeviceUID,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain,
        };

        let mut uid_ref: coreaudio_sys::CFStringRef = std::ptr::null();
        let mut size = mem::size_of::<coreaudio_sys::CFStringRef>() as u32;

        let status = unsafe {
            AudioObjectGetPropertyData(
                device_id,
                &address,
                0,
                std::ptr::null(),
                &mut size,
                &mut uid_ref as *mut _ as *mut c_void,
            )
        };

        if status != kAudioHardwareNoError as i32 || uid_ref.is_null() {
            return None;
        }

        let cf_string: CFString = unsafe { TCFType::wrap_under_get_rule(uid_ref as *const _) };
        Some(cf_string.to_string())
    }

    /// Get the name of an audio device by its ID.
    fn get_device_name(device_id: AudioDeviceID) -> Option<String> {
        use coreaudio_sys::kAudioObjectPropertyName;
        let address = AudioObjectPropertyAddress {
            mSelector: kAudioObjectPropertyName,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain,
        };

        let mut name_ref: coreaudio_sys::CFStringRef = std::ptr::null();
        let mut size = mem::size_of::<coreaudio_sys::CFStringRef>() as u32;

        let status = unsafe {
            AudioObjectGetPropertyData(
                device_id,
                &address,
                0,
                std::ptr::null(),
                &mut size,
                &mut name_ref as *mut _ as *mut c_void,
            )
        };

        if status != kAudioHardwareNoError as i32 || name_ref.is_null() {
            return None;
        }

        let cf_string: CFString = unsafe { TCFType::wrap_under_get_rule(name_ref as *const _) };
        Some(cf_string.to_string())
    }

    /// List all audio devices in the system.
    fn list_all_devices() -> Vec<AudioDeviceInfo> {
        let address = AudioObjectPropertyAddress {
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain,
        };

        let mut data_size: u32 = 0;
        let status = unsafe {
            AudioObjectGetPropertyDataSize(
                kAudioObjectSystemObject,
                &address,
                0,
                std::ptr::null(),
                &mut data_size,
            )
        };

        if status != kAudioHardwareNoError as i32 || data_size == 0 {
            error!("Failed to get audio device count: {}", status);
            return Vec::new();
        }

        let device_count = data_size as usize / mem::size_of::<AudioDeviceID>();
        let mut device_ids = vec![0u32; device_count];

        let status = unsafe {
            AudioObjectGetPropertyData(
                kAudioObjectSystemObject,
                &address,
                0,
                std::ptr::null(),
                &mut data_size,
                device_ids.as_mut_ptr() as *mut c_void,
            )
        };

        if status != kAudioHardwareNoError as i32 {
            error!("Failed to enumerate audio devices: {}", status);
            return Vec::new();
        }

        device_ids
            .iter()
            .filter_map(|&id| {
                let uid = get_device_uid(id)?;
                let name = get_device_name(id)?;
                Some(AudioDeviceInfo { id, uid, name })
            })
            .collect()
    }

    /// Find a device by name substring.
    fn find_device_by_name<'a>(
        devices: &'a [AudioDeviceInfo],
        name: &str,
    ) -> Option<&'a AudioDeviceInfo> {
        devices.iter().find(|d| d.name.contains(name))
    }

    /// Find a device by exact UID.
    fn find_device_by_uid(devices: &[AudioDeviceInfo], uid: &str) -> Option<AudioDeviceID> {
        devices.iter().find(|d| d.uid == uid).map(|d| d.id)
    }

    /// Get the current default output device ID.
    fn get_default_output_device() -> Option<AudioDeviceID> {
        let address = AudioObjectPropertyAddress {
            mSelector: kAudioHardwarePropertyDefaultOutputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain,
        };

        let mut device_id: AudioDeviceID = 0;
        let mut size = mem::size_of::<AudioDeviceID>() as u32;

        let status = unsafe {
            AudioObjectGetPropertyData(
                kAudioObjectSystemObject,
                &address,
                0,
                std::ptr::null(),
                &mut size,
                &mut device_id as *mut _ as *mut c_void,
            )
        };

        if status != kAudioHardwareNoError as i32 || device_id == 0 {
            None
        } else {
            Some(device_id)
        }
    }

    /// Set the default output device.
    fn set_default_output_device(device_id: AudioDeviceID) -> Result<(), String> {
        let address = AudioObjectPropertyAddress {
            mSelector: kAudioHardwarePropertyDefaultOutputDevice,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain,
        };

        let status = unsafe {
            AudioObjectSetPropertyData(
                kAudioObjectSystemObject,
                &address,
                0,
                std::ptr::null(),
                mem::size_of::<AudioDeviceID>() as u32,
                &device_id as *const _ as *const c_void,
            )
        };

        if status != kAudioHardwareNoError as i32 {
            Err(format!("Failed to set default output device: status={}", status))
        } else {
            info!(device_id, "Set as default output device");
            Ok(())
        }
    }

    /// Create an aggregate device with a single sub-device.
    fn create_aggregate(
        name: &str,
        uid: &str,
        sub_device_uid: &str,
    ) -> Result<AudioDeviceID, String> {
        use core_foundation::array::CFArray;
        use core_foundation::dictionary::CFDictionary;

        // Build sub-device entry
        let sub_uid_key = CFString::new(SUB_DEVICE_UID_KEY);
        let sub_uid_val = CFString::new(sub_device_uid);
        let sub_dict =
            CFDictionary::from_CFType_pairs(&[(sub_uid_key.as_CFType(), sub_uid_val.as_CFType())]);

        let sub_array = CFArray::from_CFTypes(&[sub_dict]);

        // Build main aggregate device dictionary
        let name_key = CFString::new(AGGREGATE_DEVICE_NAME_KEY);
        let name_val = CFString::new(name);
        let uid_key = CFString::new(AGGREGATE_DEVICE_UID_KEY);
        let uid_val = CFString::new(uid);
        let sub_key = CFString::new(AGGREGATE_DEVICE_SUB_LIST_KEY);
        let master_key = CFString::new(AGGREGATE_DEVICE_MASTER_KEY);
        let master_val = CFString::new(sub_device_uid);
        let private_key = CFString::new(AGGREGATE_DEVICE_PRIVATE_KEY);

        let agg_dict = CFDictionary::from_CFType_pairs(&[
            (name_key.as_CFType(), name_val.as_CFType()),
            (uid_key.as_CFType(), uid_val.as_CFType()),
            (sub_key.as_CFType(), sub_array.as_CFType()),
            (master_key.as_CFType(), master_val.as_CFType()),
            (
                private_key.as_CFType(),
                CFBoolean::false_value().as_CFType(),
            ),
        ]);

        let mut device_id: AudioDeviceID = 0;
        let status = unsafe {
            AudioHardwareCreateAggregateDevice(
                agg_dict.as_concrete_TypeRef() as coreaudio_sys::CFDictionaryRef,
                &mut device_id,
            )
        };

        // Give CoreAudio time to process
        unsafe {
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.1, 0);
        }

        if status != kAudioHardwareNoError as i32 {
            return Err(format!(
                "AudioHardwareCreateAggregateDevice failed for '{}': status={}",
                name, status
            ));
        }

        // Track for cleanup on shutdown
        if let Ok(mut created) = CREATED_DEVICES.lock() {
            created.push(device_id);
        }

        info!(device_id, name, uid, "Aggregate device created");
        Ok(device_id)
    }

    /// Create an aggregate device with multiple sub-devices (Multi-Output).
    fn create_multi_output(
        name: &str,
        uid: &str,
        sub_device_uids: &[&str],
        master_uid: &str,
    ) -> Result<AudioDeviceID, String> {
        use core_foundation::array::CFArray;
        use core_foundation::dictionary::CFDictionary;
        use core_foundation::number::CFNumber;

        // Build sub-device entries
        let sub_dicts: Vec<_> = sub_device_uids
            .iter()
            .map(|sub_uid| {
                let sub_uid_key = CFString::new(SUB_DEVICE_UID_KEY);
                let sub_uid_val = CFString::new(sub_uid);
                CFDictionary::from_CFType_pairs(&[(sub_uid_key.as_CFType(), sub_uid_val.as_CFType())])
            })
            .collect();

        let sub_array = CFArray::from_CFTypes(&sub_dicts);

        // Build main aggregate device dictionary
        let name_key = CFString::new(AGGREGATE_DEVICE_NAME_KEY);
        let name_val = CFString::new(name);
        let uid_key = CFString::new(AGGREGATE_DEVICE_UID_KEY);
        let uid_val = CFString::new(uid);
        let sub_key = CFString::new(AGGREGATE_DEVICE_SUB_LIST_KEY);
        let master_key = CFString::new(AGGREGATE_DEVICE_MASTER_KEY);
        let master_val = CFString::new(master_uid);
        let private_key = CFString::new(AGGREGATE_DEVICE_PRIVATE_KEY);
        // "stacked" = 1 means Multi-Output (all outputs get the same signal)
        let stacked_key = CFString::new("stacked");
        let stacked_val = CFNumber::from(1_i32);

        let agg_dict = CFDictionary::from_CFType_pairs(&[
            (name_key.as_CFType(), name_val.as_CFType()),
            (uid_key.as_CFType(), uid_val.as_CFType()),
            (sub_key.as_CFType(), sub_array.as_CFType()),
            (master_key.as_CFType(), master_val.as_CFType()),
            (
                private_key.as_CFType(),
                CFBoolean::false_value().as_CFType(),
            ),
            (stacked_key.as_CFType(), stacked_val.as_CFType()),
        ]);

        let mut device_id: AudioDeviceID = 0;
        let status = unsafe {
            AudioHardwareCreateAggregateDevice(
                agg_dict.as_concrete_TypeRef() as coreaudio_sys::CFDictionaryRef,
                &mut device_id,
            )
        };

        // Give CoreAudio time to process
        unsafe {
            CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.1, 0);
        }

        if status != kAudioHardwareNoError as i32 {
            return Err(format!(
                "AudioHardwareCreateAggregateDevice failed for '{}': status={}",
                name, status
            ));
        }

        // Track for cleanup on shutdown
        if let Ok(mut created) = CREATED_DEVICES.lock() {
            created.push(device_id);
        }

        info!(device_id, name, uid, "Multi-Output device created");
        Ok(device_id)
    }

    /// Destroy an aggregate device by ID.
    fn destroy_aggregate(device_id: AudioDeviceID) -> Result<(), String> {
        let status = unsafe { AudioHardwareDestroyAggregateDevice(device_id) };

        if status != kAudioHardwareNoError as i32 {
            return Err(format!(
                "AudioHardwareDestroyAggregateDevice failed for device {}: status={}",
                device_id, status
            ));
        }

        info!(device_id, "Aggregate device destroyed");
        Ok(())
    }

    /// Set up all VoxVault audio devices.
    ///
    /// Creates aggregate devices if BlackHole is installed and they don't already exist.
    /// Returns a summary of what was created/found.
    pub fn setup_audio_devices() -> SetupResult {
        let mut result = SetupResult {
            capture_device: None,
            mic_device: None,
            multi_output_device: None,
            blackhole_2ch_found: false,
            blackhole_16ch_found: false,
            errors: Vec::new(),
        };

        let devices = list_all_devices();
        info!("Found {} audio devices", devices.len());
        for d in &devices {
            info!("  Device: '{}' (uid={})", d.name, d.uid);
        }

        // Check for BlackHole installations
        let bh2 = find_device_by_name(&devices, BLACKHOLE_2CH_NAME);
        let bh16 = find_device_by_name(&devices, BLACKHOLE_16CH_NAME);

        result.blackhole_2ch_found = bh2.is_some();
        result.blackhole_16ch_found = bh16.is_some();

        if bh2.is_none() {
            let msg = "BlackHole 2ch not found. Install with: brew install blackhole-2ch";
            warn!("{}", msg);
            result.errors.push(msg.to_string());
        }

        if bh16.is_none() {
            let msg = "BlackHole 16ch not found. Install with: brew install blackhole-16ch";
            warn!("{}", msg);
            result.errors.push(msg.to_string());
        }

        // Create "VoxVault Capture" aggregate (BlackHole 2ch)
        if let Some(bh2_dev) = bh2 {
            if let Some(existing_id) = find_device_by_uid(&devices, VOXVAULT_CAPTURE_UID) {
                info!("'{}' already exists (id={}), tracking for cleanup", VOXVAULT_CAPTURE_NAME, existing_id);
                if let Ok(mut created) = CREATED_DEVICES.lock() {
                    created.push(existing_id);
                }
                result.capture_device = Some(VOXVAULT_CAPTURE_NAME.to_string());
            } else {
                match create_aggregate(
                    VOXVAULT_CAPTURE_NAME,
                    VOXVAULT_CAPTURE_UID,
                    &bh2_dev.uid,
                ) {
                    Ok(_) => {
                        result.capture_device = Some(VOXVAULT_CAPTURE_NAME.to_string());
                    }
                    Err(e) => {
                        error!("{}", e);
                        result.errors.push(e);
                    }
                }
            }
        }

        // Create "VoxVault Mic" aggregate (BlackHole 16ch)
        if let Some(bh16_dev) = bh16 {
            if let Some(existing_id) = find_device_by_uid(&devices, VOXVAULT_MIC_UID) {
                info!("'{}' already exists (id={}), tracking for cleanup", VOXVAULT_MIC_NAME, existing_id);
                if let Ok(mut created) = CREATED_DEVICES.lock() {
                    created.push(existing_id);
                }
                result.mic_device = Some(VOXVAULT_MIC_NAME.to_string());
            } else {
                match create_aggregate(
                    VOXVAULT_MIC_NAME,
                    VOXVAULT_MIC_UID,
                    &bh16_dev.uid,
                ) {
                    Ok(_) => {
                        result.mic_device = Some(VOXVAULT_MIC_NAME.to_string());
                    }
                    Err(e) => {
                        error!("{}", e);
                        result.errors.push(e);
                    }
                }
            }
        }

        // Create "VoxVault Output" multi-output (default output + BlackHole 2ch)
        // This routes system audio to both speakers/headphones AND BlackHole for capture.
        if let Some(bh2_dev) = bh2 {
            if let Some(existing_id) = find_device_by_uid(&devices, VOXVAULT_OUTPUT_UID) {
                info!("'{}' already exists (id={}), tracking for cleanup", VOXVAULT_OUTPUT_NAME, existing_id);
                if let Ok(mut created) = CREATED_DEVICES.lock() {
                    created.push(existing_id);
                }
                result.multi_output_device = Some(VOXVAULT_OUTPUT_NAME.to_string());
                // Set as default output if it isn't already
                if let Some(current_default) = get_default_output_device() {
                    if current_default != existing_id {
                        if let Ok(mut orig) = ORIGINAL_OUTPUT_DEVICE.lock() {
                            *orig = Some(current_default);
                        }
                        if let Err(e) = set_default_output_device(existing_id) {
                            warn!("Could not set VoxVault Output as default: {}", e);
                        }
                    }
                }
            } else if let Some(default_id) = get_default_output_device() {
                let default_uid = get_device_uid(default_id);
                let default_name = get_device_name(default_id);
                if let Some(ref default_uid) = default_uid {
                    // Don't create if the default output IS BlackHole (infinite loop)
                    if default_uid != &bh2_dev.uid {
                        info!(
                            "Creating Multi-Output: '{}' ({}) + BlackHole 2ch",
                            default_name.as_deref().unwrap_or("unknown"),
                            default_uid
                        );

                        // Save original default for restore on teardown
                        if let Ok(mut orig) = ORIGINAL_OUTPUT_DEVICE.lock() {
                            *orig = Some(default_id);
                        }

                        match create_multi_output(
                            VOXVAULT_OUTPUT_NAME,
                            VOXVAULT_OUTPUT_UID,
                            &[default_uid.as_str(), &bh2_dev.uid],
                            default_uid.as_str(),
                        ) {
                            Ok(mo_id) => {
                                result.multi_output_device = Some(VOXVAULT_OUTPUT_NAME.to_string());
                                // Set the multi-output as system default
                                if let Err(e) = set_default_output_device(mo_id) {
                                    warn!("Could not set VoxVault Output as default: {}", e);
                                    result.errors.push(format!("Could not set default output: {}", e));
                                } else {
                                    info!("VoxVault Output set as default system output");
                                }
                            }
                            Err(e) => {
                                error!("{}", e);
                                result.errors.push(e);
                            }
                        }
                    } else {
                        info!("Default output is already BlackHole 2ch — skipping Multi-Output");
                    }
                }
            }
        }

        result
    }

    /// Destroy all VoxVault aggregate devices created by this process.
    ///
    /// Call this on app shutdown to leave the system clean.
    pub fn teardown_audio_devices() -> TeardownResult {
        let mut result = TeardownResult {
            devices_destroyed: 0,
            errors: Vec::new(),
        };

        // Restore the original default output device BEFORE destroying aggregates
        if let Ok(mut orig) = ORIGINAL_OUTPUT_DEVICE.lock() {
            if let Some(original_id) = orig.take() {
                info!(device_id = original_id, "Restoring original default output device");
                if let Err(e) = set_default_output_device(original_id) {
                    warn!("Could not restore original output: {}", e);
                    result.errors.push(format!("Could not restore original output: {}", e));
                }
            }
        }

        let device_ids: Vec<AudioDeviceID> = {
            let mut created = CREATED_DEVICES.lock().unwrap_or_else(|e| e.into_inner());
            created.drain(..).collect()
        };

        if device_ids.is_empty() {
            info!("No VoxVault audio devices to clean up");
            return result;
        }

        info!("Destroying {} VoxVault audio device(s)", device_ids.len());

        for device_id in device_ids {
            match destroy_aggregate(device_id) {
                Ok(()) => result.devices_destroyed += 1,
                Err(e) => {
                    warn!("{}", e);
                    result.errors.push(e);
                }
            }
        }

        info!(
            destroyed = result.devices_destroyed,
            "VoxVault audio device cleanup complete"
        );
        result
    }

    /// List all devices (exposed for debugging / frontend).
    pub fn list_devices() -> Vec<AudioDeviceInfo> {
        list_all_devices()
    }
}

#[cfg(target_os = "macos")]
pub use macos::*;

#[cfg(not(target_os = "macos"))]
pub fn setup_audio_devices() -> serde_json::Value {
    serde_json::json!({
        "error": "Audio device setup is only supported on macOS"
    })
}

#[cfg(not(target_os = "macos"))]
pub fn teardown_audio_devices() -> serde_json::Value {
    serde_json::json!({
        "error": "Audio device teardown is only supported on macOS"
    })
}

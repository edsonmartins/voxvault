use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WebviewUrl, WebviewWindowBuilder,
};

const PYTHON_API: &str = "http://localhost:8766";

#[derive(Clone, serde::Serialize, serde::Deserialize)]
struct HealthStatus {
    status: String,
    rust_connected: bool,
    session_active: bool,
    translation_mode: String,
}

#[tauri::command]
async fn check_health() -> Result<HealthStatus, String> {
    let url = format!("{PYTHON_API}/api/health");
    let resp = reqwest::get(&url)
        .await
        .map_err(|e| format!("Python API unreachable: {e}"))?;
    let status: HealthStatus = resp
        .json()
        .await
        .map_err(|e| format!("Invalid response: {e}"))?;
    Ok(status)
}

#[tauri::command]
async fn set_stealth_mode(window: tauri::WebviewWindow, enabled: bool) -> Result<(), String> {
    window
        .set_content_protected(enabled)
        .map_err(|e| format!("Failed to set content protection: {e}"))?;
    Ok(())
}

#[tauri::command]
async fn get_stealth_mode(window: tauri::WebviewWindow) -> Result<bool, String> {
    let _ = window;
    Ok(true)
}

fn show_or_create_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    } else {
        let _ = WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
            .title("VoxVault")
            .inner_size(420.0, 600.0)
            .decorations(false)
            .always_on_top(true)
            .content_protected(true)
            .resizable(false)
            .center()
            .visible(true)
            .build();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .invoke_handler(tauri::generate_handler![
            check_health,
            set_stealth_mode,
            get_stealth_mode,
        ])
        .setup(|app| {
            // Build tray menu
            let show_item = MenuItem::with_id(app, "show", "Show VoxVault", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            // Build tray icon (single instance — no trayIcon in tauri.conf.json)
            let mut builder = TrayIconBuilder::new()
                .icon_as_template(true)
                .tooltip("VoxVault")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_or_create_window(app),
                    "quit" => app.exit(0),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_or_create_window(tray.app_handle());
                    }
                });

            if let Some(icon) = app.default_window_icon().cloned() {
                builder = builder.icon(icon);
            }

            let tray = builder.build(app)?;
            app.manage(tray);

            // Show window on startup
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.center();
                let _ = window.show();
                let _ = window.set_focus();
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running VoxVault");
}

mod commands;
mod python_runtime;
mod service_manager;

use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::WebviewWindowBuilder;

fn runtime_workspace_root_from(start: &Path) -> Option<PathBuf> {
    for candidate in start.ancestors() {
        if candidate.file_name().and_then(|name| name.to_str()) == Some("运行产物") {
            return candidate.parent().map(Path::to_path_buf);
        }
    }
    None
}

fn webview_data_dir_from_exe(exe_path: &Path) -> Option<PathBuf> {
    let exe_dir = exe_path.parent()?;
    let root = runtime_workspace_root_from(exe_dir)?;
    Some(
        root.join("运行产物")
            .join("桌面端WebView数据")
            .join("local.astock.backtester"),
    )
}

fn build_main_window(app: &mut tauri::App) -> tauri::Result<()> {
    let window_config = app
        .config()
        .app
        .windows
        .first()
        .expect("main window config should exist");
    let mut builder = WebviewWindowBuilder::from_config(app.handle(), window_config)?;
    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(data_dir) = webview_data_dir_from_exe(&exe_path) {
            builder = builder.data_directory(data_dir);
        }
    }
    builder.build()?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .manage(Mutex::new(service_manager::DataServiceManager::default()))
        .setup(|app| {
            build_main_window(app)?;
            #[cfg(desktop)]
            app.handle()
                .plugin(tauri_plugin_updater::Builder::new().build())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::backend_command,
            commands::ensure_data_service,
            commands::load_saved_strategies,
            commands::open_external_url,
            commands::open_ths_original_url,
            commands::persist_saved_strategies,
            commands::workspace_diagnostics
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

#[cfg(test)]
mod tests {
    use super::webview_data_dir_from_exe;
    use serde_json::Value;

    #[test]
    fn webview_data_dir_uses_runtime_artifacts_on_d_drive() {
        let exe = std::path::Path::new(
            r"D:\New project 6\运行产物\桌面软件\A股策略回测工作台\a-stock-backtester.exe",
        );

        let data_dir = webview_data_dir_from_exe(exe).expect("D runtime install tree should resolve");

        assert_eq!(
            data_dir,
            std::path::Path::new(r"D:\New project 6\运行产物\桌面端WebView数据\local.astock.backtester")
                .to_path_buf()
        );
    }

    #[test]
    fn tauri_config_leaves_main_window_for_runtime_builder() {
        let config: Value =
            serde_json::from_str(include_str!("../tauri.conf.json")).expect("tauri config should be valid json");
        let window = &config["app"]["windows"][0];

        assert_eq!(window["label"].as_str(), Some("main"));
        assert_eq!(window["create"].as_bool(), Some(false));
    }

    #[test]
    fn release_windows_binary_uses_gui_subsystem() {
        let main_rs = include_str!("main.rs");

        assert!(
            main_rs.contains(r#"cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")"#),
            "release Windows builds should not allocate a console window"
        );
    }
}

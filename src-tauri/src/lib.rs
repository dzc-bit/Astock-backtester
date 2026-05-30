mod commands;
mod python_runtime;
mod service_manager;

use std::sync::Mutex;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .manage(Mutex::new(service_manager::DataServiceManager::default()))
        .setup(|app| {
            #[cfg(desktop)]
            app.handle()
                .plugin(tauri_plugin_updater::Builder::new().build())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::backend_command,
            commands::ensure_data_service,
            commands::load_saved_strategies,
            commands::persist_saved_strategies
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

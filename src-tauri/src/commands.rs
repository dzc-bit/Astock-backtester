use serde_json::Value;
use std::io::Write;
use std::process::Stdio;
use std::sync::Mutex;
use tauri::{AppHandle, State};

use crate::python_runtime::python_command;
use crate::service_manager::{DataServiceManager, DataServiceStatus};

#[tauri::command]
pub fn ensure_data_service(
    app: AppHandle,
    cache_dir: String,
    manager: State<Mutex<DataServiceManager>>,
) -> Result<DataServiceStatus, String> {
    let mut manager = manager
        .lock()
        .map_err(|_| "data service manager lock poisoned".to_string())?;
    manager.ensure_running(&app, &cache_dir)
}

#[tauri::command]
pub fn backend_command(payload: Value) -> Result<Value, String> {
    let mut command = python_command()?;
    let mut child = command
        .args(["-m", "astock_backtester.cli"])
        .env("PYTHONPATH", "backend")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|err| format!("failed to start backend: {err}"))?;

    {
        let stdin = child.stdin.as_mut().ok_or("backend stdin unavailable")?;
        stdin
            .write_all(payload.to_string().as_bytes())
            .map_err(|err| format!("failed to write backend stdin: {err}"))?;
    }

    let output = child
        .wait_with_output()
        .map_err(|err| format!("failed to read backend output: {err}"))?;

    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).to_string());
    }

    serde_json::from_slice(&output.stdout).map_err(|err| format!("invalid backend json: {err}"))
}

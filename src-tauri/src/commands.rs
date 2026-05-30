use serde_json::Value;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Mutex;
use tauri::{AppHandle, State};

use crate::python_runtime::{backend_dir, project_root, python_command};
use crate::service_manager::{DataServiceManager, DataServiceStatus};

fn saved_strategies_path_from_root(root: &Path) -> PathBuf {
    root.join("运行产物")
        .join("策略配置")
        .join("saved-strategies.json")
}

fn read_saved_strategies_from(root: &Path) -> Result<Value, String> {
    let path = saved_strategies_path_from_root(root);
    if !path.exists() {
        return Ok(Value::Array(Vec::new()));
    }
    let raw = fs::read_to_string(&path).map_err(|err| format!("failed to read saved strategies: {err}"))?;
    let parsed: Value = serde_json::from_str(&raw).map_err(|err| format!("invalid saved strategies json: {err}"))?;
    if !parsed.is_array() {
        return Err("saved strategies must be a JSON array".to_string());
    }
    Ok(parsed)
}

fn write_saved_strategies_to(root: &Path, items: &Value) -> Result<(), String> {
    let array = items
        .as_array()
        .ok_or_else(|| "saved strategies payload must be a JSON array".to_string())?;
    let path = saved_strategies_path_from_root(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("failed to create strategy config dir: {err}"))?;
    }
    let payload = serde_json::to_string_pretty(array).map_err(|err| format!("failed to encode saved strategies: {err}"))?;
    fs::write(&path, payload).map_err(|err| format!("failed to write saved strategies: {err}"))?;
    Ok(())
}

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
    let root = project_root()?;
    let backend_path = backend_dir(&root);
    let mut command = python_command()?;
    let mut child = command
        .args(["-m", "astock_backtester.cli"])
        .current_dir(&root)
        .env("PYTHONPATH", backend_path)
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

#[tauri::command]
pub fn load_saved_strategies() -> Result<Value, String> {
    let root = project_root()?;
    read_saved_strategies_from(&root)
}

#[tauri::command]
pub fn persist_saved_strategies(items: Value) -> Result<(), String> {
    let root = project_root()?;
    write_saved_strategies_to(&root, &items)
}

#[cfg(test)]
mod tests {
    use super::{read_saved_strategies_from, saved_strategies_path_from_root, write_saved_strategies_to};
    use serde_json::json;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_temp_dir(name: &str) -> std::path::PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time should be valid")
            .as_nanos();
        std::env::temp_dir().join(format!("astock-backtester-{name}-{suffix}"))
    }

    #[test]
    fn saved_strategies_path_stays_under_runtime_strategy_config_dir() {
        let root = std::path::Path::new(r"D:\New project 6");

        assert_eq!(
            saved_strategies_path_from_root(root),
            root.join("运行产物").join("策略配置").join("saved-strategies.json")
        );
    }

    #[test]
    fn saved_strategies_round_trip_uses_json_array_file() {
        let root = unique_temp_dir("saved-strategy-storage");
        let payload = json!([
            {
                "id": "saved-1",
                "name": "示例策略",
                "saved_at": "2026-05-29T00:00:00Z",
                "strategy": {
                    "name": "示例策略",
                    "market_filters": [],
                    "entry_groups": [],
                    "exit_rules": [],
                    "score_threshold": null
                }
            }
        ]);

        write_saved_strategies_to(&root, &payload).expect("saved strategies should be written");
        let stored = read_saved_strategies_from(&root).expect("saved strategies should be read");

        assert_eq!(stored, payload);

        fs::remove_dir_all(root).expect("temp strategy config tree should be removed");
    }
}

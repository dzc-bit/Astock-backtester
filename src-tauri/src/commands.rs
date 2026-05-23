use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};

#[tauri::command]
pub fn backend_command(payload: Value) -> Result<Value, String> {
    let mut child = Command::new("python")
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

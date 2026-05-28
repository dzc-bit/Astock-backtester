use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

use crate::python_runtime::{backend_dir, project_root, python_command};

#[derive(Clone, serde::Serialize)]
pub struct DataServiceStatus {
    pub running: bool,
    pub port: u16,
    pub base_url: String,
    pub cache_dir: String,
    pub message: String,
}

struct ManagedService {
    child: Child,
    port: u16,
    cache_dir: String,
}

#[derive(Default)]
pub struct DataServiceManager {
    service: Option<ManagedService>,
}

pub fn build_service_args(port: u16, cache_dir: &str) -> Vec<String> {
    vec![
        "-m".to_string(),
        "astock_backtester.service".to_string(),
        "--host".to_string(),
        "127.0.0.1".to_string(),
        "--port".to_string(),
        port.to_string(),
        "--cache-dir".to_string(),
        cache_dir.to_string(),
    ]
}

pub fn health_request(port: u16) -> String {
    format!("GET /ping HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n")
}

fn resolve_cache_dir(cache_dir: &str) -> Result<String, String> {
    let path = Path::new(cache_dir);
    if path.is_absolute() || cfg!(debug_assertions) {
        return Ok(cache_dir.to_string());
    }
    let exe = std::env::current_exe().map_err(|err| format!("current exe unavailable: {err}"))?;
    let install_dir = exe
        .parent()
        .ok_or_else(|| "current exe parent unavailable".to_string())?;
    Ok(install_dir.join(path).to_string_lossy().to_string())
}

fn choose_port() -> Result<u16, String> {
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|err| format!("bind port failed: {err}"))?;
    let port = listener
        .local_addr()
        .map_err(|err| format!("read port failed: {err}"))?
        .port();
    drop(listener);
    Ok(port)
}

fn wait_for_health(port: u16) -> Result<(), String> {
    let deadline = Instant::now() + Duration::from_secs(8);
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", port)) {
            let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
            let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
            let _ = stream.write_all(health_request(port).as_bytes());
            let mut raw = String::new();
            let _ = stream.read_to_string(&mut raw);
            if raw.contains("200 OK") {
                return Ok(());
            }
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Err(format!("localhost data service did not become healthy on port {port}"))
}

fn packaged_service_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|err| format!("resource dir unavailable: {err}"))?;
    Ok(resource_dir.join("bin").join("astock-data-service.exe"))
}

impl DataServiceManager {
    pub fn ensure_running(&mut self, app: &AppHandle, cache_dir: &str) -> Result<DataServiceStatus, String> {
        let resolved_cache_dir = resolve_cache_dir(cache_dir)?;
        if let Some(existing) = self.service.as_mut() {
            if existing.child.try_wait().map_err(|err| err.to_string())?.is_none() {
                return Ok(DataServiceStatus {
                    running: true,
                    port: existing.port,
                    base_url: format!("http://127.0.0.1:{}", existing.port),
                    cache_dir: existing.cache_dir.clone(),
                    message: "local data service already running".to_string(),
                });
            }
            self.service = None;
        }

        let port = choose_port()?;
        let mut command = if cfg!(debug_assertions) {
            let root = project_root()?;
            let backend_path = backend_dir(&root);
            let mut python = python_command()?;
            python.args(build_service_args(port, &resolved_cache_dir));
            python.current_dir(&root);
            python.env("PYTHONPATH", backend_path);
            python
        } else {
            let mut packaged = Command::new(packaged_service_path(app)?);
            packaged.args(["--host", "127.0.0.1", "--port", &port.to_string(), "--cache-dir", &resolved_cache_dir]);
            packaged
        };
        command.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::piped());
        let child = command
            .spawn()
            .map_err(|err| format!("failed to start localhost data service: {err}"))?;
        wait_for_health(port)?;
        self.service = Some(ManagedService {
            child,
            port,
            cache_dir: resolved_cache_dir.clone(),
        });
        Ok(DataServiceStatus {
            running: true,
            port,
            base_url: format!("http://127.0.0.1:{port}"),
            cache_dir: resolved_cache_dir,
            message: "local data service started".to_string(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::{build_service_args, health_request, resolve_cache_dir};

    #[test]
    fn health_request_targets_lightweight_ping_endpoint() {
        let raw = health_request(9123);
        assert!(raw.contains("GET /ping HTTP/1.1"));
        assert!(raw.contains("Host: 127.0.0.1:9123"));
    }

    #[test]
    fn build_service_args_uses_expected_host_port_and_cache_dir() {
        let args = build_service_args(9010, ".astock-cache");
        assert_eq!(
            args,
            vec![
                "-m".to_string(),
                "astock_backtester.service".to_string(),
                "--host".to_string(),
                "127.0.0.1".to_string(),
                "--port".to_string(),
                "9010".to_string(),
                "--cache-dir".to_string(),
                ".astock-cache".to_string(),
            ]
        );
    }

    #[test]
    fn release_cache_dir_is_stable_when_input_is_relative() {
        let resolved = resolve_cache_dir(".astock-cache").expect("cache dir should resolve");

        if cfg!(debug_assertions) {
            assert_eq!(resolved, ".astock-cache");
        } else {
            assert!(std::path::Path::new(&resolved).is_absolute());
            assert!(resolved.ends_with(".astock-cache"));
        }
    }
}

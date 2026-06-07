use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};
use std::{env, fs};

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

fn dedupe_paths(candidates: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut deduped: Vec<PathBuf> = Vec::new();
    for candidate in candidates {
        let normalized = candidate.to_string_lossy().to_lowercase();
        if deduped
            .iter()
            .any(|existing| existing.to_string_lossy().to_lowercase() == normalized)
        {
            continue;
        }
        deduped.push(candidate);
    }
    deduped
}

fn workspace_cache_candidates_from_root(root: &Path, cache_dir: &str) -> Vec<PathBuf> {
    dedupe_paths(vec![
        root.join("运行产物").join("本地数据仓"),
        root.join(cache_dir),
    ])
}

fn runtime_workspace_root_from(start: &Path) -> Option<PathBuf> {
    for candidate in start.ancestors() {
        if candidate.file_name().and_then(|name| name.to_str()) == Some("运行产物") {
            if let Some(root) = candidate.parent() {
                return Some(root.to_path_buf());
            }
        }
    }
    None
}

fn runtime_data_candidates_from(start: &Path, cache_dir: &str) -> Vec<PathBuf> {
    runtime_workspace_root_from(start)
        .map(|root| workspace_cache_candidates_from_root(&root, cache_dir))
        .unwrap_or_default()
}

fn has_market_data(cache_dir: &Path) -> bool {
    let warehouse_root = cache_dir.join("warehouse").join("daily_bars");
    if let Ok(entries) = fs::read_dir(&warehouse_root) {
        for entry in entries.flatten() {
            let parquet = entry.path().join("daily_bars.parquet");
            if parquet.exists() && parquet.metadata().map(|meta| meta.len() > 0).unwrap_or(false) {
                return true;
            }
        }
    }

    let legacy_parquet = cache_dir.join("parquet").join("daily_bars.parquet");
    legacy_parquet.exists() && legacy_parquet.metadata().map(|meta| meta.len() > 0).unwrap_or(false)
}

fn choose_populated_cache_dir(preferred: &Path, candidates: &[PathBuf]) -> PathBuf {
    if has_market_data(preferred) {
        return preferred.to_path_buf();
    }

    for candidate in candidates {
        if candidate != preferred && has_market_data(candidate) {
            return candidate.clone();
        }
    }

    preferred.to_path_buf()
}

fn release_cache_candidates(cache_dir: &str) -> Vec<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(root) = project_root() {
        candidates.extend(workspace_cache_candidates_from_root(&root, cache_dir));
    }

    if let Ok(current_dir) = env::current_dir() {
        candidates.extend(runtime_data_candidates_from(&current_dir, cache_dir));
        candidates.extend(workspace_cache_candidates_from_root(&current_dir, cache_dir));
    }

    if let Ok(exe_path) = env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            candidates.extend(runtime_data_candidates_from(exe_dir, cache_dir));
        }
    }

    dedupe_paths(candidates)
}

fn resolve_cache_dir(cache_dir: &str) -> Result<String, String> {
    let path = Path::new(cache_dir);
    if path.is_absolute() || cfg!(debug_assertions) {
        return Ok(cache_dir.to_string());
    }
    let candidates = release_cache_candidates(cache_dir);
    let preferred = candidates
        .first()
        .cloned()
        .ok_or_else(|| {
            format!(
                "workspace data dir was not found; expected {} or {}",
                Path::new(r"D:\New project 6").join("运行产物").join("本地数据仓").display(),
                Path::new(r"D:\New project 6").join(cache_dir).display()
            )
        })?;
    let selected = choose_populated_cache_dir(&preferred, &candidates);
    Ok(selected.to_string_lossy().to_string())
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

fn is_healthy(port: u16) -> bool {
    wait_for_health(port).is_ok()
}

fn packaged_service_relative_path() -> PathBuf {
    PathBuf::from("bin").join("astock-data-service.exe")
}

fn packaged_service_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|err| format!("resource dir unavailable: {err}"))?;
    Ok(resource_dir.join(packaged_service_relative_path()))
}

fn should_use_packaged_service(packaged_service_exists: bool) -> bool {
    packaged_service_exists && !cfg!(debug_assertions)
}

fn stop_child_after_start_failure<T>(child: &mut Child, message: String) -> Result<T, String> {
    if child.try_wait().map_err(|err| format!("{message}; failed to inspect child: {err}"))?.is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
    Err(message)
}

impl DataServiceManager {
    pub fn ensure_running(&mut self, app: &AppHandle, cache_dir: &str) -> Result<DataServiceStatus, String> {
        let resolved_cache_dir = resolve_cache_dir(cache_dir)?;
        if let Some(existing) = self.service.as_mut() {
            if existing.child.try_wait().map_err(|err| err.to_string())?.is_none() && is_healthy(existing.port) {
                return Ok(DataServiceStatus {
                    running: true,
                    port: existing.port,
                    base_url: format!("http://127.0.0.1:{}", existing.port),
                    cache_dir: existing.cache_dir.clone(),
                    message: "local data service already running".to_string(),
                });
            }
            let _ = existing.child.kill();
            self.service = None;
        }

        let port = choose_port()?;
        let packaged_service = packaged_service_path(app)?;
        let mut command = if should_use_packaged_service(packaged_service.exists()) {
            let mut packaged = Command::new(packaged_service);
            packaged.args(["--host", "127.0.0.1", "--port", &port.to_string(), "--cache-dir", &resolved_cache_dir]);
            packaged
        } else if cfg!(debug_assertions) {
            let root = project_root()?;
            let backend_path = backend_dir(&root);
            let mut python = python_command()?;
            python.args(build_service_args(port, &resolved_cache_dir));
            python.current_dir(&root);
            python.env("PYTHONPATH", backend_path);
            python
        } else {
            return Err("packaged localhost data service was not found".to_string());
        };
        command.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::piped());
        let mut child = command
            .spawn()
            .map_err(|err| format!("failed to start localhost data service: {err}"))?;
        if let Err(err) = wait_for_health(port) {
            return stop_child_after_start_failure(&mut child, err);
        }
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
    use super::{
        build_service_args, choose_populated_cache_dir, health_request, packaged_service_relative_path,
        stop_child_after_start_failure, runtime_data_candidates_from, workspace_cache_candidates_from_root,
        should_use_packaged_service,
    };
    use std::fs;
    use std::process::{Command, Stdio};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn unique_temp_dir(name: &str) -> std::path::PathBuf {
        let suffix = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time should be valid")
            .as_nanos();
        std::env::temp_dir().join(format!("astock-backtester-{name}-{suffix}"))
    }

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
    fn workspace_cache_candidates_prefer_runtime_data_dir_before_cache_alias() {
        let root = std::path::Path::new(r"D:\New project 6");
        let candidates = workspace_cache_candidates_from_root(root, ".astock-cache");

        assert_eq!(
            candidates,
            vec![
                root.join("运行产物").join("本地数据仓"),
                root.join(".astock-cache"),
            ]
        );
    }

    #[test]
    fn runtime_data_candidates_find_workspace_data_dir_from_desktop_runtime_tree() {
        let start = std::path::Path::new(r"D:\New project 6\运行产物\桌面软件\A股策略回测工作台");
        let candidates = runtime_data_candidates_from(start, ".astock-cache");

        assert_eq!(
            candidates,
            vec![
                std::path::Path::new(r"D:\New project 6\运行产物\本地数据仓").to_path_buf(),
                std::path::Path::new(r"D:\New project 6\.astock-cache").to_path_buf(),
            ]
        );
    }

    #[test]
    fn packaged_service_relative_path_targets_bundled_sidecar() {
        let path = packaged_service_relative_path();
        assert_eq!(path, std::path::PathBuf::from("bin").join("astock-data-service.exe"));
    }

    #[test]
    fn packaged_service_preference_matches_build_mode() {
        assert_eq!(should_use_packaged_service(true), !cfg!(debug_assertions));
        assert!(!should_use_packaged_service(false));
    }

    #[test]
    fn cache_alias_is_used_only_when_preferred_cache_is_empty() {
        let root = unique_temp_dir("cache-pick-alias");
        let preferred = root.join("preferred");
        let cache_alias = root.join(".astock-cache");
        fs::create_dir_all(&preferred).expect("preferred cache dir should exist");
        let year_dir = cache_alias.join("warehouse").join("daily_bars").join("year=2026");
        fs::create_dir_all(&year_dir).expect("cache alias warehouse dir should exist");
        fs::write(year_dir.join("daily_bars.parquet"), b"alias-data").expect("cache alias parquet should exist");

        let selected = choose_populated_cache_dir(&preferred, &[preferred.clone(), cache_alias.clone()]);

        assert_eq!(selected, cache_alias);

        fs::remove_dir_all(&root).expect("temp cache tree should be removed");
    }

    #[test]
    fn release_cache_candidates_do_not_include_old_local_data_dir() {
        let root = std::path::Path::new(r"D:\New project 6");
        let candidates = workspace_cache_candidates_from_root(root, ".astock-cache");

        assert!(candidates.contains(&root.join("运行产物").join("本地数据仓")));
        assert!(candidates.contains(&root.join(".astock-cache")));
        assert!(!candidates.contains(&root.join("运行产物").join("本地数据")));
    }

    #[test]
    fn preferred_cache_stays_selected_when_it_already_has_data() {
        let root = unique_temp_dir("cache-pick-preferred");
        let preferred = root.join("preferred");
        let legacy = root.join("legacy");
        let preferred_year_dir = preferred.join("warehouse").join("daily_bars").join("year=2026");
        let legacy_year_dir = legacy.join("warehouse").join("daily_bars").join("year=2026");
        fs::create_dir_all(&preferred_year_dir).expect("preferred warehouse dir should exist");
        fs::create_dir_all(&legacy_year_dir).expect("legacy warehouse dir should exist");
        fs::write(preferred_year_dir.join("daily_bars.parquet"), b"preferred-data")
            .expect("preferred parquet should exist");
        fs::write(legacy_year_dir.join("daily_bars.parquet"), b"legacy-data").expect("legacy parquet should exist");

        let selected = choose_populated_cache_dir(&preferred, &[preferred.clone(), legacy.clone()]);

        assert_eq!(selected, preferred);

        fs::remove_dir_all(&root).expect("temp cache tree should be removed");
    }

    #[test]
    fn stop_child_after_start_failure_terminates_spawned_process() {
        let mut child = Command::new("cmd")
            .args(["/C", "ping -n 30 127.0.0.1 > nul"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("test child process should start");

        let child_id = child.id();
        let result: Result<(), String> = stop_child_after_start_failure(&mut child, "health failed".to_string());

        assert_eq!(result.unwrap_err(), "health failed");
        let status = Command::new("tasklist")
            .args(["/FI", &format!("PID eq {child_id}")])
            .output()
            .expect("tasklist should run");
        let raw = String::from_utf8_lossy(&status.stdout);
        assert!(!raw.contains(&child_id.to_string()));
    }
}

use serde_json::Value;
use std::fs;
use std::io::Write;
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, State};

use crate::python_runtime::{backend_dir, project_root, python_command};
use crate::service_manager::{DataServiceManager, DataServiceStatus};

#[derive(serde::Serialize)]
pub struct WorkspaceDiagnostics {
    pub project_root: String,
    pub canonical_project_root: Option<String>,
    pub current_dir: String,
    pub runtime_data_dir: String,
    pub runtime_data_dir_exists: bool,
    pub cache_alias: String,
    pub cache_alias_exists: bool,
    pub cache_alias_canonical: Option<String>,
    pub cache_alias_points_to_runtime_data: Option<bool>,
    pub saved_strategies_path: String,
    pub saved_strategies_exists: bool,
    pub warnings: Vec<String>,
}

fn saved_strategies_path_from_root(root: &Path) -> PathBuf {
    root.join("运行产物")
        .join("策略配置")
        .join("saved-strategies.json")
}

fn runtime_data_dir_from_root(root: &Path) -> PathBuf {
    root.join("运行产物").join("本地数据仓")
}

fn cache_alias_from_root(root: &Path) -> PathBuf {
    root.join(".astock-cache")
}

fn canonical_string(path: &Path) -> Option<String> {
    fs::canonicalize(path)
        .ok()
        .map(|canonical| canonical.to_string_lossy().to_string())
}

fn paths_equal(left: &Path, right: &Path) -> Option<bool> {
    let left = fs::canonicalize(left).ok()?;
    let right = fs::canonicalize(right).ok()?;
    Some(left.to_string_lossy().eq_ignore_ascii_case(&right.to_string_lossy()))
}

fn workspace_diagnostics_from_root(root: &Path, current_dir: &Path) -> Result<WorkspaceDiagnostics, String> {
    let runtime_data_dir = runtime_data_dir_from_root(root);
    let cache_alias = cache_alias_from_root(root);
    let saved_strategies_path = saved_strategies_path_from_root(root);
    let runtime_data_dir_exists = runtime_data_dir.exists();
    let cache_alias_exists = cache_alias.exists();
    let cache_alias_points_to_runtime_data = if cache_alias_exists && runtime_data_dir_exists {
        paths_equal(&cache_alias, &runtime_data_dir)
    } else {
        None
    };
    let mut warnings = Vec::new();
    if !runtime_data_dir_exists {
        warnings.push(format!(
            "runtime data directory is missing: {}",
            runtime_data_dir.display()
        ));
    }
    if cache_alias_exists && cache_alias_points_to_runtime_data == Some(false) {
        warnings.push(format!(
            "cache alias does not point to runtime data directory: {}",
            cache_alias.display()
        ));
    }

    Ok(WorkspaceDiagnostics {
        project_root: root.to_string_lossy().to_string(),
        canonical_project_root: canonical_string(root),
        current_dir: current_dir.to_string_lossy().to_string(),
        runtime_data_dir: runtime_data_dir.to_string_lossy().to_string(),
        runtime_data_dir_exists,
        cache_alias: cache_alias.to_string_lossy().to_string(),
        cache_alias_exists,
        cache_alias_canonical: canonical_string(&cache_alias),
        cache_alias_points_to_runtime_data,
        saved_strategies_path: saved_strategies_path.to_string_lossy().to_string(),
        saved_strategies_exists: saved_strategies_path.exists(),
        warnings,
    })
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

fn is_ths_original_article_url(url: &str) -> bool {
    const PREFIX: &str = "https://stock.10jqka.com.cn/";
    let path = match url.strip_prefix(PREFIX) {
        Some(path) => path,
        None => return false,
    };
    if path == "zaopan/" {
        return true;
    }
    !path.is_empty()
        && path.ends_with(".shtml")
        && path
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'/' | b'.' | b'_' | b'-'))
}

fn is_safe_external_http_url(url: &str) -> bool {
    if url.chars().any(|character| character.is_control() || character.is_whitespace()) {
        return false;
    };
    let Ok(parsed) = url::Url::parse(url) else {
        return false;
    };
    matches!(parsed.scheme(), "http" | "https")
        && parsed.host_str().is_some()
        && parsed.username().is_empty()
        && parsed.password().is_none()
}

fn external_open_command(url: &str) -> Command {
    #[cfg(target_os = "windows")]
    {
        let mut command = Command::new("rundll32.exe");
        command.args(["url.dll,FileProtocolHandler", url]);
        const CREATE_NO_WINDOW: u32 = 0x08000000;
        command.creation_flags(CREATE_NO_WINDOW);
        command
    }
    #[cfg(target_os = "macos")]
    {
        let mut command = Command::new("open");
        command.arg(url);
        command
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        let mut command = Command::new("xdg-open");
        command.arg(url);
        command
    }
}

fn spawn_external_url(url: &str) -> Result<(), String> {
    let mut command = external_open_command(url);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|err| format!("failed to open Tonghuashun original article: {err}"))?;
    Ok(())
}

#[tauri::command]
pub fn open_ths_original_url(url: String) -> Result<(), String> {
    if !is_ths_original_article_url(&url) {
        return Err("only Tonghuashun original article detail urls can be opened".to_string());
    }
    spawn_external_url(&url)
}

#[tauri::command]
pub fn open_external_url(url: String) -> Result<(), String> {
    if !is_safe_external_http_url(&url) {
        return Err("only http or https urls can be opened".to_string());
    }
    spawn_external_url(&url)
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

#[tauri::command]
pub fn workspace_diagnostics() -> Result<WorkspaceDiagnostics, String> {
    let root = project_root()?;
    let current_dir = std::env::current_dir().map_err(|err| format!("failed to read current dir: {err}"))?;
    workspace_diagnostics_from_root(&root, &current_dir)
}

#[cfg(test)]
mod tests {
    use super::{
        is_safe_external_http_url, is_ths_original_article_url, read_saved_strategies_from, saved_strategies_path_from_root,
        workspace_diagnostics_from_root, write_saved_strategies_to,
    };
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
    fn ths_original_article_url_accepts_real_detail_pages() {
        assert!(is_ths_original_article_url(
            "https://stock.10jqka.com.cn/20260605/c677247169.shtml"
        ));
    }

    #[test]
    fn ths_original_article_url_accepts_zaopan_source_page() {
        assert!(is_ths_original_article_url("https://stock.10jqka.com.cn/zaopan/"));
    }

    #[test]
    fn ths_original_article_url_rejects_column_pages_and_other_hosts() {
        assert!(!is_ths_original_article_url("https://stock.10jqka.com.cn/fupan/"));
        assert!(!is_ths_original_article_url(
            "https://example.com/20260605/c677247169.shtml"
        ));
        assert!(!is_ths_original_article_url(
            "http://stock.10jqka.com.cn/20260605/c677247169.shtml"
        ));
    }

    #[test]
    fn ths_original_article_url_rejects_shell_sensitive_characters() {
        assert!(!is_ths_original_article_url(
            "https://stock.10jqka.com.cn/20260605/c677247169.shtml?x=1"
        ));
        assert!(!is_ths_original_article_url(
            "https://stock.10jqka.com.cn/20260605/c677247169.shtml & calc"
        ));
        assert!(!is_ths_original_article_url(
            "https://stock.10jqka.com.cn/20260605/c677247169.shtml\n"
        ));
    }

    #[test]
    fn external_http_url_accepts_news_links_and_rejects_non_web_targets() {
        assert!(is_safe_external_http_url("https://www.cls.cn/detail/123"));
        assert!(is_safe_external_http_url("https://finance.eastmoney.com/a/202606053421.html?from=web"));
        assert!(is_safe_external_http_url(
            "http://finance.eastmoney.com/news/1345,202607053794287518.html"
        ));
        assert!(!is_safe_external_http_url("file:///C:/Windows/System32/calc.exe"));
        assert!(!is_safe_external_http_url("https://www.cls.cn/detail/123 & calc"));
        assert!(!is_safe_external_http_url("https://www.cls.cn/detail/123\n"));
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

    #[test]
    fn workspace_diagnostics_report_runtime_paths_under_project_root() {
        let root = unique_temp_dir("workspace-diagnostics");
        let runtime_data_dir = root.join("运行产物").join("本地数据仓");
        let strategy_dir = root.join("运行产物").join("策略配置");
        fs::create_dir_all(&runtime_data_dir).expect("runtime data dir should exist");
        fs::create_dir_all(&strategy_dir).expect("strategy dir should exist");

        let diagnostics = workspace_diagnostics_from_root(&root, &root)
            .expect("workspace diagnostics should be built");

        assert_eq!(diagnostics.project_root, root.to_string_lossy());
        assert!(diagnostics.runtime_data_dir.ends_with(r"运行产物\本地数据仓"));
        assert!(diagnostics.runtime_data_dir_exists);
        assert!(diagnostics.cache_alias.ends_with(".astock-cache"));
        assert!(diagnostics.saved_strategies_path.ends_with(r"运行产物\策略配置\saved-strategies.json"));
        assert!(diagnostics.warnings.is_empty());

        fs::remove_dir_all(root).expect("temp workspace tree should be removed");
    }

    #[test]
    fn workspace_diagnostics_warn_when_runtime_data_dir_is_missing() {
        let root = unique_temp_dir("workspace-diagnostics-missing-data");
        fs::create_dir_all(&root).expect("temp workspace root should exist");

        let diagnostics = workspace_diagnostics_from_root(&root, &root)
            .expect("workspace diagnostics should still be built");

        assert!(!diagnostics.runtime_data_dir_exists);
        assert!(diagnostics.warnings.iter().any(|item| item.contains("runtime data directory")));

        fs::remove_dir_all(root).expect("temp workspace tree should be removed");
    }
}

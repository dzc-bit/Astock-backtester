use serde_json::Value;
use std::fs;
use std::io::{Read, Write};
#[cfg(windows)]
use std::os::windows::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};
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
    validate_strategy_array(&parsed)?;
    Ok(parsed)
}

/// Validate that every entry in the strategy array has the required shape.
/// Rejecting early prevents a malformed entry from ever being persisted.
fn validate_strategy_array(array: &Value) -> Result<(), String> {
    fn require_string(object: &serde_json::Map<String, Value>, field: &str, path: &str) -> Result<(), String> {
        if object.get(field).and_then(Value::as_str).is_some_and(|value| !value.is_empty()) {
            Ok(())
        } else {
            Err(format!("{path}.{field} 必须是非空字符串。"))
        }
    }

    fn validate_condition(condition: &Value, path: &str) -> Result<(), String> {
        let object = condition
            .as_object()
            .ok_or_else(|| format!("{path} 必须是 condition 对象。"))?;
        require_string(object, "id", path)?;
        require_string(object, "condition_id", path)?;
        if !object.get("enabled").is_some_and(Value::is_boolean) {
            return Err(format!("{path}.enabled 必须是布尔值。"));
        }
        if !object.get("params").is_some_and(Value::is_object) {
            return Err(format!("{path}.params 必须是对象。"));
        }
        if !object.get("data_lag_days").is_some_and(Value::is_number) {
            return Err(format!("{path}.data_lag_days 必须是数字。"));
        }
        Ok(())
    }

    let entries = array.as_array().expect("caller must guarantee array");
    for (index, entry) in entries.iter().enumerate() {
        let obj = entry.as_object().ok_or_else(|| {
            format!("已保存策略条目 #{index} 非法：期望一个 JSON 对象。")
        })?;
        if obj.get("id").and_then(|v| v.as_str()).is_none() {
            return Err(format!("已保存策略条目 #{index} 缺少必需的 id 字段（字符串）。"));
        }
        if obj.get("name").and_then(|v| v.as_str()).is_none() {
            return Err(format!("已保存策略条目 #{index} 缺少必需的 name 字段（字符串）。"));
        }
        if obj.get("saved_at").and_then(|v| v.as_str()).is_none() {
            return Err(format!("已保存策略条目 #{index} 缺少必需的 saved_at 字段（字符串）。"));
        }
        let strategy = obj.get("strategy").ok_or_else(|| {
            format!("已保存策略条目 #{index} 缺少必需的 strategy 字段。")
        })?;
        let strat_obj = strategy.as_object().ok_or_else(|| {
            format!("已保存策略条目 #{index} 的 strategy 必须是对象。")
        })?;
        require_string(strat_obj, "name", &format!("已保存策略条目 #{index}.strategy"))?;
        if !strat_obj.get("market_filters").map_or(false, |v| v.is_array()) {
            return Err(format!(
                "已保存策略条目 #{index} 的 strategy.market_filters 必须是数组。"
            ));
        }
        if !strat_obj.get("entry_groups").map_or(false, |v| v.is_array()) {
            return Err(format!(
                "已保存策略条目 #{index} 的 strategy.entry_groups 必须是数组。"
            ));
        }
        if !strat_obj.get("exit_rules").map_or(false, |v| v.is_array()) {
            return Err(format!(
                "已保存策略条目 #{index} 的 strategy.exit_rules 必须是数组。"
            ));
        }
        for (condition_index, condition) in strat_obj["market_filters"].as_array().unwrap().iter().enumerate() {
            validate_condition(condition, &format!("已保存策略条目 #{index}.strategy.market_filters[{condition_index}]"))?;
        }
        for (group_index, group) in strat_obj["entry_groups"].as_array().unwrap().iter().enumerate() {
            let path = format!("已保存策略条目 #{index}.strategy.entry_groups[{group_index}]");
            let group_object = group.as_object().ok_or_else(|| format!("{path} 必须是 group 对象。"))?;
            require_string(group_object, "id", &path)?;
            if !matches!(group_object.get("operator").and_then(Value::as_str), Some("and" | "or" | "score")) {
                return Err(format!("{path}.operator 必须是 and、or 或 score。"));
            }
            let conditions = group_object
                .get("conditions")
                .and_then(Value::as_array)
                .ok_or_else(|| format!("{path}.conditions 必须是数组。"))?;
            for (condition_index, condition) in conditions.iter().enumerate() {
                validate_condition(condition, &format!("{path}.conditions[{condition_index}]"))?;
            }
        }
        for (condition_index, condition) in strat_obj["exit_rules"].as_array().unwrap().iter().enumerate() {
            validate_condition(condition, &format!("已保存策略条目 #{index}.strategy.exit_rules[{condition_index}]"))?;
        }
    }
    Ok(())
}

/// Cross-process exclusive write lock for the saved-strategies file.
///
/// Uses `fs2::FileExt::lock_exclusive` on a companion `.lock` file so that
/// two independent application processes cannot simultaneously read-modify-write
/// and overwrite each other's changes.  The process-internal `Mutex` serialises
/// threads within a single process; this lock extends that serialisation across
/// separate OS processes.
struct SavedStrategiesFileLock {
    _file: std::fs::File,
}

impl SavedStrategiesFileLock {
    fn acquire(root: &Path) -> Result<Self, String> {
        let lock_path = saved_strategies_lock_path_from_root(root);
        if let Some(parent) = lock_path.parent() {
            fs::create_dir_all(parent)
                .map_err(|err| format!("failed to create lock dir: {err}"))?;
        }
        let file = std::fs::OpenOptions::new()
            .create(true)
            .write(true)
            .truncate(false)
            .open(&lock_path)
            .map_err(|err| format!("failed to open saved-strategies lock file: {err}"))?;
        fs2::FileExt::lock_exclusive(&file)
            .map_err(|err| format!("failed to acquire saved-strategies cross-process lock: {err}"))?;
        Ok(Self { _file: file })
    }
}

impl Drop for SavedStrategiesFileLock {
    fn drop(&mut self) {
        // fs2 releases the lock when the file descriptor is closed.
        let _ = fs2::FileExt::unlock(&self._file);
    }
}

fn saved_strategies_lock_path_from_root(root: &Path) -> PathBuf {
    root.join("运行产物")
        .join("策略配置")
        .join("saved-strategies.lock")
}

/// Dedicated synchronization boundary for saved-strategies writes.
///
/// Serializes every write within this process so concurrent atomic strategy
/// mutations cannot interleave.
fn saved_strategies_write_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

/// Build a process-unique temporary path next to the final file. Keeps a `.tmp`
/// suffix so any leaked temporary remains easy to detect and clean up.
fn unique_tmp_path(path: &Path) -> PathBuf {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let seq = COUNTER.fetch_add(1, Ordering::Relaxed);
    let pid = std::process::id();
    path.with_extension(format!("json.{pid}.{seq}.tmp"))
}

fn write_saved_strategies_unlocked(root: &Path, items: &Value) -> Result<(), String> {
    // Validate and encode the payload BEFORE touching disk. An invalid (non-array)
    // payload must never destroy or truncate the existing file.
    let array = items
        .as_array()
        .ok_or_else(|| "saved strategies payload must be a JSON array".to_string())?;
    validate_strategy_array(items)?;
    let payload = serde_json::to_string_pretty(array).map_err(|err| format!("failed to encode saved strategies: {err}"))?;

    let path = saved_strategies_path_from_root(root);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("failed to create strategy config dir: {err}"))?;
    }

    // Atomic write: write_all + sync_all to a unique .tmp first, then rename
    // over the final path.  On any failure, clean up the temp file so nothing
    // is leaked and the previous file stays intact (the rename either fully
    // succeeds or never happens).
    let tmp_path = unique_tmp_path(&path);
    {
        let mut tmp_file = std::fs::File::create(&tmp_path)
            .map_err(|err| {
                let _ = fs::remove_file(&tmp_path);
                format!("failed to create tmp strategies file: {err}")
            })?;
        tmp_file.write_all(payload.as_bytes()).map_err(|err| {
            let _ = fs::remove_file(&tmp_path);
            format!("failed to write tmp strategies: {err}")
        })?;
        tmp_file.sync_all().map_err(|err| {
            let _ = fs::remove_file(&tmp_path);
            format!("failed to sync tmp strategies to disk: {err}")
        })?;
    }
    if let Err(err) = fs::rename(&tmp_path, &path) {
        if let Err(cleanup_err) = fs::remove_file(&tmp_path) {
            return Err(format!(
                "failed to rename tmp strategies ({err}), and cleanup of tmp file also failed ({cleanup_err})"
            ));
        }
        return Err(format!("failed to rename tmp strategies: {err}, tmp file cleaned up"));
    }
    Ok(())
}

#[cfg(test)]
fn write_saved_strategies_to(root: &Path, items: &Value) -> Result<(), String> {
    let _file_lock = SavedStrategiesFileLock::acquire(root)?;
    let _guard = saved_strategies_write_lock()
        .lock()
        .map_err(|_| "saved strategies write lock poisoned".to_string())?;
    write_saved_strategies_unlocked(root, items)
}

fn upsert_saved_strategy_in(root: &Path, preset: Value) -> Result<Value, String> {
    let new_id = preset
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| "preset must have a string 'id'".to_string())?;
    let _file_lock = SavedStrategiesFileLock::acquire(root)?;
    let _guard = saved_strategies_write_lock()
        .lock()
        .map_err(|_| "saved strategies write lock poisoned".to_string())?;
    let mut current = read_saved_strategies_from(root)?;
    let array = current
        .as_array_mut()
        .ok_or_else(|| "saved strategies must be a JSON array".to_string())?;
    if let Some(pos) = array
        .iter()
        .position(|entry| entry.get("id").and_then(Value::as_str) == Some(new_id))
    {
        array[pos] = preset;
    } else {
        array.insert(0, preset);
    }
    write_saved_strategies_unlocked(root, &current)?;
    Ok(current)
}

fn delete_saved_strategy_in(root: &Path, preset_id: &str) -> Result<Value, String> {
    let _file_lock = SavedStrategiesFileLock::acquire(root)?;
    let _guard = saved_strategies_write_lock()
        .lock()
        .map_err(|_| "saved strategies write lock poisoned".to_string())?;
    let mut current = read_saved_strategies_from(root)?;
    let array = current
        .as_array_mut()
        .ok_or_else(|| "saved strategies must be a JSON array".to_string())?;
    let before = array.len();
    array.retain(|entry| entry.get("id").and_then(Value::as_str) != Some(preset_id));
    if array.len() != before {
        write_saved_strategies_unlocked(root, &current)?;
    }
    Ok(current)
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

/// Upper bound for one fallback backend CLI invocation.  Without it a hung
/// Python process would leave the frontend waiting forever.
const BACKEND_COMMAND_TIMEOUT_SECS: u64 = 300;

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
    // Signal EOF so the CLI cannot block waiting for more payload bytes.
    drop(child.stdin.take());

    // Drain the pipes on worker threads; a full stdout pipe would otherwise
    // deadlock the child while this thread waits for it to exit.
    let mut stdout_pipe = child.stdout.take().ok_or("backend stdout unavailable")?;
    let mut stderr_pipe = child.stderr.take().ok_or("backend stderr unavailable")?;
    let stdout_reader = thread::spawn(move || {
        let mut buffer = Vec::new();
        let _ = stdout_pipe.read_to_end(&mut buffer);
        buffer
    });
    let stderr_reader = thread::spawn(move || {
        let mut buffer = Vec::new();
        let _ = stderr_pipe.read_to_end(&mut buffer);
        buffer
    });

    let deadline = Instant::now() + Duration::from_secs(BACKEND_COMMAND_TIMEOUT_SECS);
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                if Instant::now() >= deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    // The pipe-reader threads are left to finish on their own:
                    // kill closes the pipes, so their read_to_end returns EOF.
                    return Err(format!(
                        "backend command timed out after {BACKEND_COMMAND_TIMEOUT_SECS}s"
                    ));
                }
                thread::sleep(Duration::from_millis(50));
            }
            Err(err) => return Err(format!("failed to wait for backend: {err}")),
        }
    };

    let stdout = stdout_reader.join().unwrap_or_default();
    let stderr = stderr_reader.join().unwrap_or_default();

    if !status.success() {
        return Err(String::from_utf8_lossy(&stderr).to_string());
    }

    serde_json::from_slice(&stdout).map_err(|err| format!("invalid backend json: {err}"))
}

#[tauri::command]
pub fn load_saved_strategies() -> Result<Value, String> {
    let root = project_root()?;
    read_saved_strategies_from(&root)
}

/// Upsert a single saved strategy preset atomically.
///
/// Re-reads the latest disk array under the cross-process lock, inserts or
/// replaces the entry identified by `preset.id`, and writes the result
/// atomically.  Returns the new authoritative array so the frontend can
/// update its optimistic view.
#[tauri::command]
pub fn upsert_saved_strategy(preset: Value) -> Result<Value, String> {
    let root = project_root()?;
    upsert_saved_strategy_in(&root, preset)
}

/// Delete a single saved strategy preset atomically.
///
/// Re-reads the latest disk array under the cross-process lock, removes the
/// entry identified by `preset_id`, and writes the result atomically.
/// Returns the new authoritative array.
#[tauri::command]
pub fn delete_saved_strategy(preset_id: String) -> Result<Value, String> {
    let root = project_root()?;
    delete_saved_strategy_in(&root, &preset_id)
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
        is_safe_external_http_url, is_ths_original_article_url, read_saved_strategies_from,
        saved_strategies_path_from_root, validate_strategy_array,
        workspace_diagnostics_from_root, write_saved_strategies_to, upsert_saved_strategy_in,
    };
    use serde_json::{json, Value};
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
        let root = unique_temp_dir("saved-strategies-path");

        assert_eq!(
            saved_strategies_path_from_root(&root),
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
    fn write_saved_strategies_leaves_no_temp_file_behind() {
        let root = unique_temp_dir("saved-strategy-atomic");
        let payload = json!([
            {
                "id": "saved-atomic",
                "name": "原子写入测试",
                "saved_at": "2026-07-11T00:00:00Z",
                "strategy": {
                    "name": "原子写入测试",
                    "market_filters": [],
                    "entry_groups": [],
                    "exit_rules": [],
                    "score_threshold": null
                }
            }
        ]);

        write_saved_strategies_to(&root, &payload).expect("write should succeed");

        let path = saved_strategies_path_from_root(&root);
        let parent = path.parent().expect("parent dir should exist");
        let tmp_files: Vec<_> = fs::read_dir(parent)
            .expect("should read dir")
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.file_name()
                    .to_str()
                    .map(|n| n.ends_with(".tmp"))
                    .unwrap_or(false)
            })
            .collect();
        assert!(
            tmp_files.is_empty(),
            "atomic write must not leave .tmp files behind"
        );

        let stored = read_saved_strategies_from(&root).expect("read should succeed");
        assert_eq!(stored, payload);

        fs::remove_dir_all(root).expect("temp tree should be removed");
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

    #[test]
    fn write_saved_strategies_cleans_up_tmp_when_rename_fails() {
        // Force the atomic rename to fail by making the destination a NON-EMPTY directory.
        // MOVEFILE_REPLACE_EXISTING only replaces files, never directories, so the rename errors.
        let root = unique_temp_dir("saved-strategy-rename-fail");
        let path = saved_strategies_path_from_root(&root);
        fs::create_dir_all(&path).expect("destination dir should be created");
        fs::write(path.join("keep.txt"), b"keep").expect("marker file should be written");

        let payload = json!([
            {
                "id": "rename-fail",
                "name": "重命名失败测试",
                "saved_at": "2026-07-11T00:00:00Z",
                "strategy": {
                    "name": "重命名失败测试",
                    "market_filters": [],
                    "entry_groups": [],
                    "exit_rules": [],
                    "score_threshold": null
                }
            }
        ]);

        let result = write_saved_strategies_to(&root, &payload);
        assert!(result.is_err(), "rename onto a directory must fail");

        let parent = path.parent().expect("parent dir should exist");
        let tmp_files: Vec<_> = fs::read_dir(parent)
            .expect("should read dir")
            .filter_map(|entry| entry.ok())
            .filter(|entry| {
                entry
                    .file_name()
                    .to_str()
                    .map(|name| name.contains(".tmp"))
                    .unwrap_or(false)
            })
            .collect();
        assert!(
            tmp_files.is_empty(),
            "a failed rename must clean up the temporary file"
        );

        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn write_saved_strategies_preserves_original_when_payload_is_not_array() {
        let root = unique_temp_dir("saved-strategy-invalid-payload");
        let original = json!([
            {
                "id": "original",
                "name": "原始策略",
                "saved_at": "2026-07-11T00:00:00Z",
                "strategy": {
                    "name": "原始策略",
                    "market_filters": [],
                    "entry_groups": [],
                    "exit_rules": [],
                    "score_threshold": null
                }
            }
        ]);
        write_saved_strategies_to(&root, &original).expect("initial write should succeed");

        let invalid = json!({ "not": "an array" });
        let result = write_saved_strategies_to(&root, &invalid);
        assert!(result.is_err(), "a non-array payload must be rejected");

        let stored = read_saved_strategies_from(&root).expect("original file should still be readable");
        assert_eq!(
            stored, original,
            "rejecting an invalid payload must never overwrite the existing file"
        );

        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn concurrent_writes_leave_a_valid_json_array_file() {
        let root = unique_temp_dir("saved-strategy-concurrent");
        let payloads: Vec<Value> = (0..8)
            .map(|index| {
                json!([
                    {
                        "id": format!("saved-{index}"),
                        "name": format!("并发策略{index}"),
                        "saved_at": "2026-07-11T00:00:00Z",
                        "strategy": {
                            "name": format!("并发策略{index}"),
                            "market_filters": [],
                            "entry_groups": [],
                            "exit_rules": [],
                            "score_threshold": null
                        }
                    }
                ])
            })
            .collect();

        let mut handles = Vec::new();
        for payload in payloads.clone() {
            let root = root.clone();
            handles.push(std::thread::spawn(move || {
                write_saved_strategies_to(&root, &payload).expect("concurrent write should succeed");
            }));
        }
        for handle in handles {
            handle.join().expect("write thread should not panic");
        }

        let stored = read_saved_strategies_from(&root).expect("final file should be a valid json array");
        assert!(stored.is_array(), "final file must be a valid json array");
        assert!(
            payloads.contains(&stored),
            "serialized writes must leave the file equal to one complete payload (no interleaving)"
        );

        fs::remove_dir_all(root).ok();
    }

    // ------------------------------------------------------------------
    // Round-4: strategy persistence hardening
    // ------------------------------------------------------------------

    #[test]
    fn validate_strategy_rejects_null_entry() {
        let array = json!([null]);
        let err = super::validate_strategy_array(&array).unwrap_err();
        assert!(err.contains("期望一个 JSON 对象"));
    }

    #[test]
    fn validate_strategy_rejects_missing_id() {
        let array = json!([{
            "name": "测试",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": "测试",
                "market_filters": [],
                "entry_groups": [],
                "exit_rules": [],
                "score_threshold": null
            }
        }]);
        let err = super::validate_strategy_array(&array).unwrap_err();
        assert!(err.contains("id"));
    }

    #[test]
    fn validate_strategy_rejects_strategy_not_object() {
        let array = json!([{
            "id": "test-1",
            "name": "测试",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": null
        }]);
        let err = super::validate_strategy_array(&array).unwrap_err();
        assert!(err.contains("strategy 必须是对象"));
    }

    #[test]
    fn validate_strategy_rejects_missing_market_filters() {
        let array = json!([{
            "id": "test-1",
            "name": "测试",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": "测试",
                "entry_groups": [],
                "exit_rules": []
            }
        }]);
        let err = super::validate_strategy_array(&array).unwrap_err();
        assert!(err.contains("market_filters"));
    }

    #[test]
    fn validate_strategy_rejects_incomplete_nested_condition() {
        let array = json!([{
            "id": "test-1",
            "name": "测试",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": "测试",
                "market_filters": [{"id": "condition-1"}],
                "entry_groups": [{"id": "g", "operator": "and", "conditions": [{}]}],
                "exit_rules": []
            }
        }]);
        let err = super::validate_strategy_array(&array).unwrap_err();
        assert!(err.contains("condition_id"), "unexpected validation error: {err}");
    }

    #[test]
    fn upsert_inserts_new_preset_and_returns_full_array() {
        let root = unique_temp_dir("saved-strategy-upsert");
        // Start with one existing entry
        let existing = json!([{
            "id": "existing-1",
            "name": "既有策略",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": "既有策略",
                "market_filters": [],
                "entry_groups": [],
                "exit_rules": [],
                "score_threshold": null
            }
        }]);
        write_saved_strategies_to(&root, &existing).expect("initial write should succeed");

        let new_preset = json!({
            "id": "new-1",
            "name": "新策略",
            "saved_at": "2026-07-11T01:00:00Z",
            "strategy": {
                "name": "新策略",
                "market_filters": [],
                "entry_groups": [],
                "exit_rules": [],
                "score_threshold": null
            }
        });

        // Simulate upsert logic: read, insert, write, return
        let mut current = read_saved_strategies_from(&root).expect("should read");
        let array = current.as_array_mut().unwrap();
        array.insert(0, new_preset.clone());
        let updated = Value::Array(array.clone());
        validate_strategy_array(&updated).expect("should validate");
        write_saved_strategies_to(&root, &updated).expect("should write");

        assert_eq!(updated.as_array().unwrap().len(), 2);
        assert_eq!(updated[0]["id"], "new-1");
        assert_eq!(updated[1]["id"], "existing-1");

        let stored = read_saved_strategies_from(&root).expect("should read");
        assert_eq!(stored, updated);

        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn delete_removes_existing_preset_and_returns_remaining() {
        let root = unique_temp_dir("saved-strategy-delete");
        let payload = json!([
            {
                "id": "keep-me",
                "name": "保留",
                "saved_at": "2026-07-11T00:00:00Z",
                "strategy": {
                    "name": "保留",
                    "market_filters": [],
                    "entry_groups": [],
                    "exit_rules": [],
                    "score_threshold": null
                }
            },
            {
                "id": "remove-me",
                "name": "删除",
                "saved_at": "2026-07-11T00:00:00Z",
                "strategy": {
                    "name": "删除",
                    "market_filters": [],
                    "entry_groups": [],
                    "exit_rules": [],
                    "score_threshold": null
                }
            }
        ]);
        write_saved_strategies_to(&root, &payload).expect("initial write should succeed");

        let mut current = read_saved_strategies_from(&root).expect("should read");
        let array = current.as_array_mut().unwrap();
        array.retain(|entry| entry.get("id").and_then(|v| v.as_str()) != Some("remove-me"));
        write_saved_strategies_to(&root, &current).expect("should write");

        let stored = read_saved_strategies_from(&root).expect("should read");
        assert_eq!(stored.as_array().unwrap().len(), 1);
        assert_eq!(stored[0]["id"], "keep-me");

        fs::remove_dir_all(root).ok();
    }

    fn valid_saved_strategy(id: &str) -> Value {
        json!({
            "id": id,
            "name": id,
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": id,
                "market_filters": [],
                "entry_groups": [],
                "exit_rules": [],
                "score_threshold": null
            }
        })
    }

    #[test]
    fn atomic_upsert_core_preserves_concurrent_updates() {
        let root = unique_temp_dir("saved-strategy-concurrent-upsert");
        let first_root = root.clone();
        let second_root = root.clone();
        let first = std::thread::spawn(move || {
            upsert_saved_strategy_in(&first_root, valid_saved_strategy("first"))
                .expect("first upsert should complete")
        });
        let second = std::thread::spawn(move || {
            upsert_saved_strategy_in(&second_root, valid_saved_strategy("second"))
                .expect("second upsert should complete")
        });

        first.join().expect("first upsert thread should not panic");
        second.join().expect("second upsert thread should not panic");
        let stored = read_saved_strategies_from(&root).expect("saved strategies should be readable");
        let ids: Vec<_> = stored
            .as_array()
            .expect("saved strategies should be an array")
            .iter()
            .filter_map(|item| item.get("id").and_then(Value::as_str))
            .collect();
        assert!(ids.contains(&"first"));
        assert!(ids.contains(&"second"));
        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn write_all_and_sync_all_are_used_on_tmp_file() {
        let root = unique_temp_dir("saved-strategy-sync");
        let payload = json!([{
            "id": "sync-test",
            "name": "同步测试",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": "同步测试",
                "market_filters": [],
                "entry_groups": [],
                "exit_rules": [],
                "score_threshold": null
            }
        }]);

        write_saved_strategies_to(&root, &payload).expect("write should succeed");

        let stored = read_saved_strategies_from(&root).expect("read should succeed");
        assert_eq!(stored, payload);

        // Verify no .tmp files remain (cleanup succeeded)
        let parent = saved_strategies_path_from_root(&root).parent().unwrap().to_path_buf();
        let tmp_count = fs::read_dir(&parent)
            .unwrap()
            .filter(|e| {
                e.as_ref()
                    .ok()
                    .and_then(|entry| entry.file_name().to_str().map(|n| n.ends_with(".tmp")))
                    .unwrap_or(false)
            })
            .count();
        assert_eq!(tmp_count, 0, "no .tmp files should remain after successful write");

        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn rename_failure_cleanup_error_is_included_in_message() {
        let root = unique_temp_dir("saved-strategy-rename-cleanup");
        let path = saved_strategies_path_from_root(&root);
        fs::create_dir_all(&path).expect("destination dir should be created");
        fs::write(path.join("keep.txt"), b"keep").expect("marker file should be written");

        let payload = json!([{
            "id": "rename-cleanup",
            "name": "重命名清理测试",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": "重命名清理测试",
                "market_filters": [],
                "entry_groups": [],
                "exit_rules": [],
                "score_threshold": null
            }
        }]);

        let result = write_saved_strategies_to(&root, &payload);
        assert!(result.is_err());
        let err_msg = result.unwrap_err();
        // The error message must describe the rename failure AND, if cleanup also
        // failed, mention it.  If cleanup succeeded, mention that the tmp was cleaned.
        assert!(
            err_msg.contains("rename") || err_msg.contains("Rename"),
            "error must describe the rename failure: {err_msg}"
        );
        // At minimum, the error message must not claim "保证清理" without
        // acknowledging the actual outcome.
        assert!(
            !err_msg.contains("保证清理"),
            "error message must not claim guaranteed cleanup: {err_msg}"
        );

        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn read_saved_strategies_rejects_corrupt_strategy_fields() {
        let root = unique_temp_dir("saved-strategy-corrupt-fields");
        let corrupt = json!([{
            "id": "corrupt",
            "name": "损坏策略",
            "saved_at": "2026-07-11T00:00:00Z",
            "strategy": {
                "name": "损坏策略",
                "market_filters": "not-an-array",
                "entry_groups": 42,
                "exit_rules": null
            }
        }]);
        let path = saved_strategies_path_from_root(&root);
        fs::create_dir_all(path.parent().unwrap()).expect("dir should be created");
        fs::write(&path, serde_json::to_string_pretty(&corrupt).unwrap()).expect("write corrupt file");

        let result = read_saved_strategies_from(&root);
        assert!(result.is_err(), "corrupt strategy fields must cause load failure");
        assert!(result.unwrap_err().contains("market_filters"));

        fs::remove_dir_all(root).ok();
    }
}

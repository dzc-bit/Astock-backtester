use std::path::{Path, PathBuf};
use std::process::Command;

fn backend_marker(root: &Path) -> PathBuf {
    root.join("backend")
        .join("astock_backtester")
        .join("__init__.py")
}

pub fn resolve_project_root_from(start: &Path) -> Option<PathBuf> {
    for candidate in start.ancestors() {
        if backend_marker(candidate).exists() {
            return Some(candidate.to_path_buf());
        }
    }
    None
}

pub fn project_root() -> Result<PathBuf, String> {
    if let Ok(value) = std::env::var("ASTOCK_BACKTESTER_PROJECT_ROOT") {
        let path = PathBuf::from(value);
        if backend_marker(&path).exists() {
            return Ok(path);
        }
    }

    if let Ok(current_dir) = std::env::current_dir() {
        if let Some(path) = resolve_project_root_from(&current_dir) {
            return Ok(path);
        }
    }

    if let Ok(exe_path) = std::env::current_exe() {
        if let Some(exe_dir) = exe_path.parent() {
            if let Some(path) = resolve_project_root_from(exe_dir) {
                return Ok(path);
            }
        }
    }

    Err("project root was not found; expected backend/astock_backtester under the workspace root".to_string())
}

pub fn backend_dir(root: &Path) -> PathBuf {
    root.join("backend")
}

pub fn bundled_python_path(root: &Path) -> PathBuf {
    root.join(".tools").join("python-3.11.9").join("python.exe")
}

pub fn python_command() -> Result<Command, String> {
    if let Ok(path) = std::env::var("ASTOCK_BACKTESTER_PYTHON") {
        return Ok(Command::new(path));
    }

    if let Ok(root) = project_root() {
        let bundled = bundled_python_path(&root);
        if bundled.exists() {
            return Ok(Command::new(bundled));
        }
    }

    if Command::new("python").arg("--version").output().is_ok() {
        return Ok(Command::new("python"));
    }
    if Command::new("py").args(["-3", "--version"]).output().is_ok() {
        let mut command = Command::new("py");
        command.arg("-3");
        return Ok(command);
    }
    Err("python runtime was not found; set ASTOCK_BACKTESTER_PYTHON".to_string())
}

#[cfg(test)]
mod tests {
    use super::{backend_dir, bundled_python_path, resolve_project_root_from};
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
    fn resolves_project_root_from_nested_runtime_directory() {
        let root = unique_temp_dir("project-root");
        let runtime_dir = root.join("运行产物").join("桌面软件");
        let backend_dir_path = root.join("backend").join("astock_backtester");
        fs::create_dir_all(&runtime_dir).expect("runtime dir should exist");
        fs::create_dir_all(&backend_dir_path).expect("backend dir should exist");
        fs::write(backend_dir_path.join("__init__.py"), "").expect("marker file should exist");

        let resolved = resolve_project_root_from(&runtime_dir).expect("project root should resolve");
        assert_eq!(resolved, root);

        fs::remove_dir_all(&root).expect("temp tree should be removed");
    }

    #[test]
    fn backend_dir_and_bundled_python_stay_under_project_root() {
        let root = std::path::Path::new(r"D:\New project 6");

        assert_eq!(backend_dir(root), root.join("backend"));
        assert_eq!(
            bundled_python_path(root),
            root.join(".tools").join("python-3.11.9").join("python.exe")
        );
    }
}

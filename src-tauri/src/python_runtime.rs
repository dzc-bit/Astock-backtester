use std::process::Command;

pub fn python_command() -> Result<Command, String> {
    if let Ok(path) = std::env::var("ASTOCK_BACKTESTER_PYTHON") {
        return Ok(Command::new(path));
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

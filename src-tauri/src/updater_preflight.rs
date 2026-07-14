use serde::Serialize;
use serde_json::Value;
use std::fmt::Display;
use std::time::Duration;
use url::Url;

const PREFLIGHT_TIMEOUT: Duration = Duration::from_secs(10);

fn ensure_rustls_provider() {
    if rustls::crypto::CryptoProvider::get_default().is_none() {
        let _ = rustls::crypto::ring::default_provider().install_default();
    }
}

#[derive(Debug, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum UpdatePreflight {
    Http { endpoint: String, status: u16 },
    Network { endpoint: String, message: String },
}

pub fn updater_endpoint_from_config(updater_config: &Value) -> Result<Url, String> {
    let endpoint = updater_config
        .get("endpoints")
        .and_then(Value::as_array)
        .and_then(|endpoints| endpoints.first())
        .and_then(Value::as_str)
        .ok_or_else(|| "updater config must include a non-empty endpoints array".to_string())?;

    Url::parse(endpoint).map_err(|error| format!("invalid updater endpoint: {error}"))
}

pub fn preflight_from_status(endpoint: &Url, status: u16) -> UpdatePreflight {
    UpdatePreflight::Http {
        endpoint: endpoint.to_string(),
        status,
    }
}

pub fn preflight_from_error(endpoint: &Url, error: impl Display) -> UpdatePreflight {
    UpdatePreflight::Network {
        endpoint: endpoint.to_string(),
        message: error.to_string(),
    }
}

async fn fetch_preflight(endpoint: Url) -> UpdatePreflight {
    ensure_rustls_provider();
    let client = match reqwest::Client::builder().timeout(PREFLIGHT_TIMEOUT).build() {
        Ok(client) => client,
        Err(error) => return preflight_from_error(&endpoint, error),
    };

    match client.get(endpoint.as_str()).send().await {
        Ok(response) => preflight_from_status(&endpoint, response.status().as_u16()),
        Err(error) => preflight_from_error(&endpoint, error),
    }
}

#[tauri::command]
pub async fn updater_preflight(app: tauri::AppHandle) -> Result<UpdatePreflight, String> {
    let updater_config = app
        .config()
        .plugins
        .0
        .get("updater")
        .ok_or_else(|| "updater config is missing".to_string())?;
    let endpoint = updater_endpoint_from_config(updater_config)?;

    Ok(fetch_preflight(endpoint).await)
}

#[cfg(test)]
mod tests {
    use super::{
        ensure_rustls_provider, preflight_from_error, preflight_from_status,
        updater_endpoint_from_config, UpdatePreflight,
    };
    use serde_json::{json, Value};
    use url::Url;

    #[test]
    fn installs_the_rustls_provider_before_creating_the_preflight_client() {
        ensure_rustls_provider();

        assert!(rustls::crypto::CryptoProvider::get_default().is_some());
    }

    #[test]
    fn resolves_the_configured_updater_endpoint() {
        let config: Value = serde_json::from_str(include_str!("../tauri.conf.json"))
            .expect("tauri config should be valid JSON");
        let endpoint = updater_endpoint_from_config(&config["plugins"]["updater"])
            .expect("updater endpoint should resolve from config");

        assert_eq!(
            endpoint.as_str(),
            "https://github.com/dzc-bit/Astock-backtester/releases/latest/download/latest.json"
        );
    }

    #[test]
    fn preserves_http_statuses_for_frontend_retry_classification() {
        let endpoint = Url::parse("https://updates.example.test/latest.json").expect("valid endpoint");

        assert_eq!(
            preflight_from_status(&endpoint, 404),
            UpdatePreflight::Http {
                endpoint: endpoint.to_string(),
                status: 404
            }
        );
        assert_eq!(
            preflight_from_status(&endpoint, 503),
            UpdatePreflight::Http {
                endpoint: endpoint.to_string(),
                status: 503
            }
        );
        assert!(updater_endpoint_from_config(&json!({ "endpoints": [] })).is_err());
    }

    #[test]
    fn preserves_network_failures_for_frontend_retry_classification() {
        let endpoint = Url::parse("https://updates.example.test/latest.json").expect("valid endpoint");

        assert_eq!(
            preflight_from_error(&endpoint, "connection timed out"),
            UpdatePreflight::Network {
                endpoint: endpoint.to_string(),
                message: "connection timed out".to_string(),
            }
        );
    }
}

from __future__ import annotations

from astock_backtester.ai.config import AiConfig, AiConfigStore, ai_base_dir_from_cache_dir, masked_key


def test_masked_key():
    assert masked_key("") == ""
    assert masked_key("sk-abcdefgh") == "sk-a****efgh"
    assert masked_key("short") == "*****"


def test_store_missing_file_returns_empty_config(tmp_path):
    store = AiConfigStore(tmp_path)
    config = store.load()
    assert config.is_configured() is False
    assert config.base_url == ""


def test_save_roundtrip_and_key_preservation(tmp_path):
    store = AiConfigStore(tmp_path)
    saved = store.save(AiConfig(base_url="https://api.example.com/v1", api_key="sk-secret-key", model="demo-model"))
    assert saved.is_configured() is True
    assert store.load().api_key == "sk-secret-key"

    # Empty key on update means "keep the existing key"
    updated = store.save(AiConfig(base_url="https://api2.example.com/v1", model="m2"))
    assert updated.api_key == "sk-secret-key"
    assert updated.base_url == "https://api2.example.com/v1"
    assert updated.model == "m2"


def test_masked_view_never_leaks_key(tmp_path):
    store = AiConfigStore(tmp_path)
    store.save(AiConfig(base_url="https://api.example.com", api_key="sk-abcdef123456", model="m"))
    view = store.masked_view()
    assert view["configured"] is True
    assert "sk-abcdef123456" not in str(view)
    assert view["api_key_masked"].startswith("sk-a")


def test_config_defaults_left_blank(tmp_path):
    store = AiConfigStore(tmp_path)
    view = store.masked_view()
    assert view["configured"] is False
    assert view["base_url"] == ""
    assert view["model"] == ""


def test_ai_base_dir_prefers_writable_parent(tmp_path):
    warehouse = tmp_path / "本地数据仓"
    warehouse.mkdir()
    base = ai_base_dir_from_cache_dir(warehouse)
    assert base == tmp_path

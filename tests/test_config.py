from nekofetch.core.config import AppConfig


def test_defaults_when_missing_file(tmp_path):
    cfg = AppConfig.load(tmp_path / "nope.yaml")
    assert cfg.features.request_system is True
    assert cfg.downloads.concurrent_downloads == 5
    assert cfg.sources.default == "telegram"
    # New channel sections default to disabled.
    assert cfg.storage_channel.enabled is False
    assert cfg.log_channel.enabled is False


def test_loads_real_project_config():
    cfg = AppConfig.load("config.yaml")
    assert "local" in cfg.sources.enabled
    assert isinstance(cfg.branding.channel_name, str)

import os
import pytest

from lib.config import Config, load_config


# Minimal set of required env vars with valid values
REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "123456:ABC-DEF",
    "TELEGRAM_WEBHOOK_SECRET": "whsec_test_secret_value_long_enough",
    "TELEGRAM_CHAT_IDS": "111,222",
    "BOT_PASSWORD": "s3cret",
    "DATABASE_URL": "postgresql://user:pass@localhost/axiom",
    "OPENROUTER_API_KEY": "sk-or-test-key",
    "CRON_SECRET": "cron_test_secret",
    "ALLOWED_TOPICS": "momentum,volatility forecasting,factor model",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Remove all config-related env vars before each test."""
    for key in list(os.environ):
        if key in REQUIRED_ENV or key in (
            "DEFAULT_MODEL", "DEEPDIVE_MODEL", "DEEPDIVE_DAY",
            "ARXIV_CATEGORIES", "ARXIV_MAX_RESULTS",
            "RELEVANCE_THRESHOLD", "QUALITY_GATE_MIN",
            "DEDUP_SIMILARITY_MAX", "MAX_IDEAS_PER_DAY",
        ):
            monkeypatch.delenv(key, raising=False)


def _set_required(monkeypatch):
    """Set all required env vars to valid test values."""
    for key, val in REQUIRED_ENV.items():
        monkeypatch.setenv(key, val)


class TestLoadConfigHappyPath:

    def test_returns_config_instance(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert isinstance(cfg, Config)

    def test_required_fields_populated(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.telegram_bot_token == "123456:ABC-DEF"
        assert cfg.bot_password == "s3cret"
        assert cfg.database_url == "postgresql://user:pass@localhost/axiom"
        assert cfg.openrouter_api_key == "sk-or-test-key"
        assert cfg.cron_secret == "cron_test_secret"


class TestLoadConfigRequiredVars:

    @pytest.mark.parametrize("missing_key", list(REQUIRED_ENV.keys()))
    def test_missing_required_var_raises(self, monkeypatch, missing_key):
        _set_required(monkeypatch)
        monkeypatch.delenv(missing_key)
        with pytest.raises(EnvironmentError, match=missing_key):
            load_config()

    def test_empty_required_var_raises(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        with pytest.raises(EnvironmentError, match="TELEGRAM_BOT_TOKEN"):
            load_config()

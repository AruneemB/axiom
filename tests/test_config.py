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


class TestLoadConfigDefaults:

    def test_default_model(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.default_model == "google/gemini-flash-1.5"

    def test_default_deepdive_model(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.deepdive_model == "anthropic/claude-3-5-haiku-20241022"

    def test_default_deepdive_day(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.deepdive_day == 4

    def test_default_arxiv_categories(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.arxiv_categories == ["q-fin.PM", "q-fin.ST"]

    def test_default_arxiv_max_results(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.arxiv_max_results == 50

    def test_default_relevance_threshold(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.relevance_threshold == 0.65

    def test_default_quality_gate_min(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.quality_gate_min == 13

    def test_default_dedup_similarity_max(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.dedup_similarity_max == 0.80

    def test_default_max_ideas_per_day(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.max_ideas_per_day == 2


class TestLoadConfigOverrides:

    def test_override_default_model(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("DEFAULT_MODEL", "openai/gpt-4o-mini")
        cfg = load_config()
        assert cfg.default_model == "openai/gpt-4o-mini"

    def test_override_deepdive_day(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("DEEPDIVE_DAY", "0")
        cfg = load_config()
        assert cfg.deepdive_day == 0

    def test_override_relevance_threshold(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("RELEVANCE_THRESHOLD", "0.80")
        cfg = load_config()
        assert cfg.relevance_threshold == 0.80

    def test_override_max_ideas_per_day(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("MAX_IDEAS_PER_DAY", "5")
        cfg = load_config()
        assert cfg.max_ideas_per_day == 5


class TestLoadConfigTypeCasting:

    def test_chat_ids_parsed_as_int_list(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.telegram_chat_ids == [111, 222]
        assert all(isinstance(x, int) for x in cfg.telegram_chat_ids)

    def test_single_chat_id(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("TELEGRAM_CHAT_IDS", "999")
        cfg = load_config()
        assert cfg.telegram_chat_ids == [999]

    def test_allowed_topics_split(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert cfg.allowed_topics == ["momentum", "volatility forecasting", "factor model"]

    def test_arxiv_categories_custom(self, monkeypatch):
        _set_required(monkeypatch)
        monkeypatch.setenv("ARXIV_CATEGORIES", "cs.AI,cs.LG,stat.ML")
        cfg = load_config()
        assert cfg.arxiv_categories == ["cs.AI", "cs.LG", "stat.ML"]

    def test_float_fields_are_float(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert isinstance(cfg.relevance_threshold, float)
        assert isinstance(cfg.dedup_similarity_max, float)

    def test_int_fields_are_int(self, monkeypatch):
        _set_required(monkeypatch)
        cfg = load_config()
        assert isinstance(cfg.deepdive_day, int)
        assert isinstance(cfg.arxiv_max_results, int)
        assert isinstance(cfg.quality_gate_min, int)
        assert isinstance(cfg.max_ideas_per_day, int)

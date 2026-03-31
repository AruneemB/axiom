import os
from dataclasses import dataclass


@dataclass
class Config:
    telegram_bot_token: str
    telegram_webhook_secret: str
    telegram_chat_ids: list[int]
    bot_password: str
    database_url: str
    openrouter_api_key: str
    default_model: str
    fallback_model: str
    deepdive_model: str
    deepdive_day: int
    cron_secret: str
    arxiv_categories: list[str]
    arxiv_max_results: int
    allowed_topics: list[str]
    relevance_threshold: float
    quality_gate_min: int
    dedup_similarity_max: float
    embedding_model: str
    max_ideas_per_day: int
    openrouter_timeout: int


def load_config() -> Config:
    def require(key: str) -> str:
        val = os.environ.get(key)
        if not val:
            raise EnvironmentError(f"Required env var {key} is not set")
        return val

    return Config(
        telegram_bot_token=require("TELEGRAM_BOT_TOKEN"),
        telegram_webhook_secret=require("TELEGRAM_WEBHOOK_SECRET"),
        telegram_chat_ids=[int(x) for x in require("TELEGRAM_CHAT_IDS").split(",")],
        bot_password=require("BOT_PASSWORD"),
        database_url=require("DATABASE_URL"),
        openrouter_api_key=require("OPENROUTER_API_KEY"),
        default_model=os.getenv("DEFAULT_MODEL", "google/gemini-2.5-flash"),
        fallback_model=os.getenv("FALLBACK_MODEL", "google/gemini-2.0-flash"),
        deepdive_model=os.getenv("DEEPDIVE_MODEL", "anthropic/claude-3-5-haiku-20241022"),
        deepdive_day=int(os.getenv("DEEPDIVE_DAY", "4")),
        cron_secret=require("CRON_SECRET"),
        arxiv_categories=os.getenv("ARXIV_CATEGORIES", "q-fin.PM,q-fin.ST").split(","),
        arxiv_max_results=int(os.getenv("ARXIV_MAX_RESULTS", "50")),
        allowed_topics=require("ALLOWED_TOPICS").split(","),
        relevance_threshold=float(os.getenv("RELEVANCE_THRESHOLD", "0.55")),
        quality_gate_min=int(os.getenv("QUALITY_GATE_MIN", "11")),
        dedup_similarity_max=float(os.getenv("DEDUP_SIMILARITY_MAX", "0.80")),
        embedding_model=os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small"),
        max_ideas_per_day=int(os.getenv("MAX_IDEAS_PER_DAY", "2")),
        openrouter_timeout=int(os.getenv("OPENROUTER_TIMEOUT", "90")),
    )

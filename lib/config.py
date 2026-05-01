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
    deliver_llm_timeout: int

    # Chat feature settings
    chat_enabled: bool
    chat_model: str
    chat_context_window: int
    chat_max_messages_per_session: int
    chat_max_active_sessions_per_user: int
    chat_max_messages_per_hour: int
    chat_session_timeout_hours: int
    chat_max_tokens_per_user_per_day: int

    # GitHub integration settings
    github_token: str
    github_repo_owner: str
    github_repo_name: str
    github_issue_labels: list[str]
    max_github_issues_per_day: int

    # Security settings
    telegram_ip_allowlist_enabled: bool

    # Semantic Scholar enrichment
    semantic_scholar_api_key: str
    citation_weight: float


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
        openrouter_timeout=int(os.getenv("OPENROUTER_TIMEOUT", "50")),
        deliver_llm_timeout=int(os.getenv("DELIVER_LLM_TIMEOUT", "50")),

        # Chat feature
        chat_enabled=os.getenv("CHAT_ENABLED", "true").lower() == "true",
        chat_model=os.getenv("CHAT_MODEL", "google/gemini-flash-1.5"),
        chat_context_window=int(os.getenv("CHAT_CONTEXT_WINDOW", "10")),
        chat_max_messages_per_session=int(os.getenv("CHAT_MAX_MESSAGES_PER_SESSION", "20")),
        chat_max_active_sessions_per_user=int(os.getenv("CHAT_MAX_ACTIVE_SESSIONS_PER_USER", "5")),
        chat_max_messages_per_hour=int(os.getenv("CHAT_MAX_MESSAGES_PER_HOUR", "20")),
        chat_session_timeout_hours=int(os.getenv("CHAT_SESSION_TIMEOUT_HOURS", "2")),
        chat_max_tokens_per_user_per_day=int(os.getenv("CHAT_MAX_TOKENS_PER_USER_PER_DAY", "50000")),

        # GitHub integration
        github_token=os.getenv("GITHUB_TOKEN", ""),
        github_repo_owner=os.getenv("GITHUB_REPO_OWNER", "aruneemb"),
        github_repo_name=os.getenv("GITHUB_REPO_NAME", "axiom"),
        github_issue_labels=os.getenv("GITHUB_ISSUE_LABELS", "user-reported,needs-triage").split(","),
        max_github_issues_per_day=int(os.getenv("MAX_GITHUB_ISSUES_PER_DAY", "3")),

        # Security settings
        telegram_ip_allowlist_enabled=os.getenv("TELEGRAM_IP_ALLOWLIST_ENABLED", "false").lower() == "true",

        # Semantic Scholar enrichment
        semantic_scholar_api_key=os.getenv("SEMANTIC_SCHOLAR_API_KEY", ""),
        citation_weight=float(os.getenv("CITATION_WEIGHT", "0.02")),
    )

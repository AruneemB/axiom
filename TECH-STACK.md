# Axiom Tech Stack

The following technologies power the Axiom pipeline, chosen for their zero-cost tier availability, high reliability, and minimal maintenance requirements.

## Core Language & Runtime

- **Python 3.11+**: The core logic is built with modern, type-annotated Python.
- **Vercel Serverless Functions**: Provides a serverless execution environment with zero infrastructure management. Key endpoints (`api/fetch`, `api/spark`) use a 300-second `maxDuration` to accommodate long-running LLM calls.
- **Vercel Cron**: Scheduled triggers for daily ingestion (06:00 UTC) and delivery (08:00 UTC).

## Data & Vectors

- **Neon Postgres**: A serverless PostgreSQL database that scales to zero when not in use.
- **pgvector**: Enables vector similarity search within Postgres, allowing for semantic filtering of research abstracts at **1536 dimensions**.
- **OpenRouter Embeddings**: Uses `openai/text-embedding-3-small` via OpenRouter to generate 1536-dimensional embeddings for research abstracts and idea deduplication.

## Intelligence Layer

- **OpenRouter**: Unified API access to state-of-the-art LLMs, primarily:
    - **Google Gemini 2.5 Flash** (`google/gemini-2.5-flash`): Efficient, high-throughput daily processing and on-demand synthesis.
    - **Anthropic Claude 3.5 Haiku** (`anthropic/claude-3-5-haiku-20241022`): Deep-dive synthesis on Fridays for higher-quality ideation.
    - **Google Gemini Flash 1.5** (`google/gemini-flash-1.5`): Powers the interactive `/chat` sessions and the public "Ask Axiom" chatbot widget.
- **Fallback Routing**: Automatic retry with a configurable `FALLBACK_MODEL` (default: `google/gemini-2.0-flash`) on LLM timeouts.

## External Data Sources

- **arXiv API**: Polls quantitative finance and machine learning categories over a rolling 7-day window. Papers are filtered by keyword and semantic similarity before storage.
- **Semantic Scholar Graph API**: After arXiv ingestion, Axiom calls the [Semantic Scholar batch endpoint](https://api.semanticscholar.org/graph/v1/paper/batch) to retrieve citation counts for newly stored papers. These counts are stored in `papers.citation_count` and applied as a log-scaled ranking boost at delivery time. The API is free for low-volume usage; an optional `SEMANTIC_SCHOLAR_API_KEY` raises the rate limit from 1 to 10 requests/second.

## Communication & Delivery

- **Telegram Bot API**: Delivers real-time research alerts with inline feedback buttons, and handles commands including `/spark`, `/chat`, `/report`, `/pause`, `/resume`, `/status`, `/topics`, and `/feedback`.
- **GitHub REST API** (via PyGithub): Creates structured, AI-triaged issues from `/report` submissions, with security validation applied before any GitHub call.
- **Httpx**: Modern, fully-featured HTTP client for all outbound API interactions (arXiv, Semantic Scholar, Telegram, OpenRouter).

## Security

- **HMAC Webhook Verification**: Telegram webhook payloads are verified using constant-time HMAC comparison (`lib/security_validator`).
- **Multi-Layer Input Validation**: `/report` submissions pass through profanity, PII, and injection-detection checks before reaching the GitHub API.
- **Rate Limiting**: `/spark` is rate-limited per user. The `/chat` endpoint enforces per-session, per-hour, and per-day token limits.
- **IP Allowlisting**: Optional `TELEGRAM_IP_ALLOWLIST_ENABLED` restricts webhook ingress to Telegram's published IP ranges.

## Quality Assurance

- **Pytest**: Comprehensive unit test suite covering all core modules and API handlers.
- **Pytest-Httpx**: For mocking external HTTP calls during testing.
- **Pydantic**: Robust data validation at system boundaries.

## Support Libraries

- **NumPy**: Efficient numerical computations and cosine similarity logic.
- **Psycopg2**: Reliable PostgreSQL adapter for Python.
- **Feedparser**: For processing Atom XML feeds from arXiv.
- **Python-Dateutil**: Precise handling of international time zones and paper timestamps.
- **PyGithub**: Integration with the GitHub REST API for issue management.

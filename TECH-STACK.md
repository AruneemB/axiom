# Axiom Tech Stack

The following technologies power the Axiom pipeline, chosen for their zero-cost tier availability, high reliability, and minimal maintenance requirements.

## Core Language & Runtime

- **Python 3.11+**: The core logic is built with modern, asynchronous-ready Python.
- **Vercel Serverless Functions**: Provides a serverless execution environment with zero infrastructure management.
- **Vercel Cron**: Scheduled triggers for daily ingestion and delivery.

## Data & Vectors

- **Neon Postgres**: A serverless PostgreSQL database that scales to zero when not in use.
- **pgvector**: Enables vector similarity search within Postgres, allowing for semantic filtering of research abstracts.
- **Sentence-Transformers**: Uses the `all-MiniLM-L6-v2` model to generate 384-dimensional embeddings for research abstracts.

## Intelligence Layer

- **OpenRouter**: Unified API access to state-of-the-art LLMs, primarily:
    - **Google Gemini 1.5 Flash**: Efficient, high-throughput daily processing.
    - **Anthropic Claude 3.5 Haiku**: Deep-dive synthesis and higher-quality ideation.

## Communication & Delivery

- **Telegram Bot API**: Delivers real-time research alerts and collects interactive user feedback.
- **Httpx**: Modern, fully-featured HTTP client for all API interactions (arXiv, Telegram, OpenRouter).

## Quality Assurance

- **Pytest**: Comprehensive unit and integration testing suite.
- **Pytest-Httpx**: For mocking external API calls during testing.
- **Pydantic**: Robust data validation and settings management.

## Support Libraries

- **NumPy**: Efficient numerical computations and cosine similarity logic.
- **Psycopg2**: Reliable PostgreSQL adapter for Python.
- **Feedparser**: For processing Atom XML feeds from arXiv.
- **Python-Dateutil**: Precise handling of international time zones and paper timestamps.

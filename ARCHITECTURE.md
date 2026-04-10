# Axiom Architecture

Axiom is a serverless, event-driven pipeline designed for quantitative research synthesis. It operates on a daily cycle, transforming raw academic papers into actionable trading hypotheses with zero infrastructure overhead.

## System Overview

```mermaid
graph TD
    A[arXiv API] -->|Daily Fetch| B(api/fetch)
    B -->|Filter 1: Keywords| C{Relevance Filter}
    B -->|Filter 2: Embeddings| C
    C -->|Store Relevant| D[(Neon Postgres)]
    
    E[cron-job.org] -->|Trigger| B
    E -->|Trigger| F(api/deliver)
    
    F -->|Query Queued| D
    D -->|Paper Abstract| G[OpenRouter LLM]
    G -->|Hypothesis + Method| H{Quality Gate}
    H -->|Pass| I[Telegram Delivery]
    
    I -->|User Feedback| J(api/telegram)
    J -->|Update Weights| D
    J -->|Personalize| C
    
    I -->|/chat Command| J
    J -->|Interactive Session| L[lib/chat]
    L -->|Contextual Prompt| G
    
    I -->|/report Command| J
    J -->|Security Check| M[lib/security_validator]
    M -->|Create Issue| N[GitHub API]
    
    I -->|/spark Command| J
    J -->|Trigger| K(api/spark)
    K -->|Query or Fetch| D
    K -->|Paper Abstract| G
```

## Core Components

### 1. Ingestion & Filtering (`api/fetch`)
- **arXiv Client**: Polls specific categories (e.g., `q-fin.PM`, `q-fin.ST`) for papers published in the last 36 hours.
- **Two-Stage Filter**:
    - **Keyword Matching**: Fast pre-filtering against a dynamic list of topics.
    - **Vector Similarity**: Uses OpenRouter embeddings (`openai/text-embedding-3-small`) to compare paper abstracts against a "Seed Corpus" of high-quality reference papers stored in `pgvector`.
- **Deduplication**: Ensures the same paper isn't processed twice across overlapping windows.

### 2. Synthesis (`api/deliver`)
- **LLM Orchestration**: Routes abstracts to OpenRouter (defaulting to Gemini 1.5 Flash for speed/cost, with Claude 3.5 Haiku for "Deep Dive" sessions).
- **Structured Extraction**: The system prompt enforces a rigorous "Senior Quant" persona, focusing on methodology, data requirements, and feasibility.
- **Scoring**: Every idea is assigned a **Novelty** and **Feasibility** score (1-10).
- **Quality Gate**: Only ideas exceeding a combined threshold (default: 13/20) are delivered.

### 3. Delivery & Feedback (`api/telegram`)
- **Interactive Interface**: Ideas are delivered via Telegram Bot API with inline buttons for feedback ("Interesting" vs. "Skip").
- **Dynamic Weighting**:
    - "Interesting" (+1) increases the weight of matching keywords in the database.
    - "Skip" (-1) decreases weights.
- **Personalization**: These weights are applied as multipliers during the next day's filtering stage, allowing Axiom to "learn" your research preferences over time.
- **Command Handling**: Processes bot commands like `/spark` (which triggers `api/spark` for on-demand generation) and `/status`.

### 4. Data Layer (Neon Postgres)
- **Relational Schema**: Manages papers, ideas, authorized users, feedback, and **conversation sessions**.
- **Vector Search**: Leverages `pgvector` for efficient cosine similarity searches in **1536-dimensional** space.
- **Automated Migrations**: SQL-based schema management for easy deployment.
- **Topic Auto-Sync**: The database automatically stays in sync with your configured `ALLOWED_TOPICS` environment variable whenever fetch or spark endpoints are called.

### 5. Research Chat (`lib/chat`)
- **Session Management**: Tracks context across multiple messages per research idea.
- **Contextual Retrieval**: Automatically injects paper abstracts and current idea details into the LLM context.
- **Rate Limiting**: Multi-tier limits (per session, per hour, per day) to prevent API abuse.

### 6. GitHub Issue Integration (`lib/github_client`)
- **Security Validation**: A multi-layer pipeline (`lib/security_validator`) checks for profanity, PII, and injection attempts before submission.
- **AI-Powered Triaging**: Uses LLMs to generate concise issue titles and format detailed markdown bodies with technical context.
- **Traceability**: Submissions are linked to the specific research session and Telegram user for easy debugging.

### 7. On-Demand Synthesis (`api/spark`)
- **Instant Generation**: Triggered by the `/spark` Telegram command to instantly generate a new hypothesis outside the daily schedule.
- **Fallback Search Strategy**: Searches sequentially for: unprocessed papers, processed but un-sparked papers, a fresh 7-day arXiv fetch, and finally previously skipped papers.
- **Auto-Syncing**: Guarantees the user's topics are synchronized to the database before processing.
- **Resilience**: Retry logic with configurable fallback model (`FALLBACK_MODEL`) and tunable timeout (`OPENROUTER_TIMEOUT`).

### 8. Landing Page & Public API (`api/status`, `api/papers`, `api/chat`)
- **Status Endpoint**: Returns live system health, total paper/idea counts, and last fetch/deliver timestamps.
- **Papers Endpoint**: Returns the 20 most recent non-skipped papers (title, categories, arXiv URL, fetched timestamp). Unauthenticated, CORS-enabled.
- **Chat Endpoint** (`api/chat`): Stateless `POST` endpoint that answers visitor questions about the codebase and architecture. Calls OpenRouter with an inlined system prompt; no auth, no DB, no additional dependencies.
- **Interactive Landing Page**: A static page (`public/`) showing system status, a topic ticker, an expandable papers drawer, and an "Ask Axiom" chatbot widget backed by `api/chat`.

## Security & Reliability
- **Webhook Secrets**: Verifies Telegram payloads using HMAC constant-time comparison.
- **Cron Authentication**: API endpoints verify `CRON_SECRET` via `Authorization: Bearer` header (used by Vercel cron) or `?key=` query parameter (for manual invocation).
- **Serverless Resilience**: Distributed across Vercel's global edge network, minimizing latency and eliminating single points of failure.
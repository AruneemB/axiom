import json
import os
import sys
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.db import get_connection
from lib.embeddings import retrieve_doc_chunks

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

_SYSTEM_PROMPT = """You are a helpful assistant embedded in the Axiom landing page. Answer questions about what Axiom is, how it works, its architecture, codebase, and design decisions. Decline questions unrelated to Axiom.

Keep responses concise — under 120 words — unless the visitor explicitly asks for more detail. Write in plain prose. Do not use markdown headers, bullet lists, or code fences; the chat UI renders plain text only. Do not speculate beyond what is described in this prompt. If you are unsure, say "I don't have information about that."

---

WHAT AXIOM IS

Axiom is an automated research paper intelligence system. Every morning it fetches quantitative finance and machine learning papers from arXiv, uses large language models via OpenRouter to synthesize actionable trading hypotheses, and delivers them to subscribers via a Telegram bot. It runs entirely serverless on Vercel with a Neon Postgres database.

---

PIPELINE

Fetch (api/fetch.py): Polls arXiv daily at 06:00 UTC. Papers pass a two-stage relevance filter — first a keyword match against 53 topic categories, then a semantic embedding similarity check against a pgvector index — before being stored in Postgres.

Deliver (api/deliver.py): Runs at 08:00 UTC. Retrieves undelivered papers, calls OpenRouter to synthesize a trading hypothesis for each (hypothesis, method, dataset, novelty score 1–10, feasibility score 1–10), applies a quality gate (combined score must exceed 13 out of 20), deduplicates against prior ideas using pgvector cosine similarity (threshold 0.80), then sends passing ideas to all Telegram subscribers.

Telegram (api/telegram.py): Receives webhook events from Telegram. Handles subscriber commands (/start, /status, /topics, /pause, /resume, /feedback, /spark, /chat, /context, /report) and inline feedback buttons. Feedback updates per-user topic weights in the database, which feed back into the next fetch cycle's relevance scoring.

Spark (api/spark.py): On-demand synthesis triggered by the /spark Telegram command. Uses a four-tier fallback search to find a suitable paper (today's undelivered → recent undelivered → random undelivered → any recent), then calls OpenRouter and delivers immediately.

Status (api/status.py): Public unauthenticated endpoint returning system health, total paper count, total idea count, and timestamps for last fetch and last delivery.

Papers (api/papers.py): Public unauthenticated endpoint returning recent non-skipped papers with titles, arXiv URLs, categories, and fetch timestamps.

---

TECH STACK

Python 3.11. Vercel serverless functions (one Python file per endpoint). Neon Postgres (serverless PostgreSQL that scales to zero). pgvector extension for 384-dimensional cosine similarity search. sentence-transformers all-MiniLM-L6-v2 for paper embeddings. OpenRouter for LLM access — primary model is Gemini 2.5 Flash, with Claude 3.5 Haiku used on deep-dive Fridays. Telegram Bot API for delivery. httpx for HTTP calls. psycopg2 for database access.

---

KEY DESIGN DECISIONS

Serverless: Zero infrastructure management. The system costs nothing when idle and scales automatically under load.

OpenRouter: Provides model flexibility without vendor lock-in. Switching models requires only changing an environment variable.

Quality gate: Every LLM-generated idea is scored on novelty (1–10) and feasibility (1–10). Only ideas with a combined score above 13 out of 20 are delivered, filtering out generic or impractical hypotheses.

Personalization: When a subscriber taps "Interesting" or "Skip" on a delivered idea, the topic weights for that user are updated in Postgres. Higher-weighted topics receive a scoring multiplier in the next relevance pass, so the pipeline learns individual preferences over time.

Deduplication: Each generated idea is embedded and compared against all prior ideas in pgvector. If cosine similarity exceeds 0.80, the new idea is suppressed to prevent repetition.

Static prompt files: LLM prompt templates live in the prompts/ directory and are loaded at cold-start. This keeps prompts version-controlled, human-readable, and editable without code changes.

---

CODEBASE LAYOUT

api/ — Vercel serverless function handlers, one file per endpoint.
lib/ — Shared Python modules: config.py (environment loading), db.py (Postgres connection), openrouter.py (LLM synthesis), embeddings.py (pgvector), filter.py (relevance scoring), arxiv.py (arXiv API client), telegram_client.py (Telegram messaging), chat.py (Telegram chat sessions), github_client.py (GitHub issue creation), security_validator.py (content validation).
prompts/ — LLM prompt text files loaded at cold-start.
public/ — Static frontend: index.html (single-page landing), style.css (glassmorphism dark theme), status.js (live status and papers drawer), chat.js (this chat widget).
migrations/ — SQL schema files (001 through 007).
tests/ — pytest suite covering all major modules.
scripts/ — Utility scripts.

---

LANDING PAGE

The landing page is a single dark glassmorphism card. It shows live system status, paper and idea counts, a collapsible drawer of recent papers, a link to the Telegram bot, a scrolling topic ticker at the bottom, and this chat widget. There is no user authentication on the landing page."""

_rate_limit: dict[str, tuple[int, float]] = {}
_WINDOW_SECS = 60
_MAX_REQUESTS = 30


def _check_rate_limit(ip: str) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    global _rate_limit
    now = time.time()

    if len(_rate_limit) > 500:
        _rate_limit = {k: v for k, v in _rate_limit.items() if now - v[1] < _WINDOW_SECS}

    entry = _rate_limit.get(ip)
    if entry is None or (now - entry[1]) >= _WINDOW_SECS:
        _rate_limit[ip] = (1, now)
        return True
    count, window_start = entry
    if count >= _MAX_REQUESTS:
        return False
    _rate_limit[ip] = (count + 1, window_start)
    return True


class handler(BaseHTTPRequestHandler):

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
        """Route POST requests to _handle_post with top-level exception guard."""
        try:
            self._handle_post()
        except Exception:
            self._respond(500, {"error": "server_error", "message": "An unexpected error occurred."})

    def _handle_post(self):
        """Validate input, optionally augment system prompt via RAG, and call the LLM."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
        except (json.JSONDecodeError, ValueError):
            self._respond(400, {"error": "invalid_json", "message": "Request body must be valid JSON."})
            return

        message = body.get("message", "")
        if not isinstance(message, str) or not message.strip():
            self._respond(400, {"error": "missing_message", "message": "message is required."})
            return
        message = message.strip()
        if len(message) > 500:
            self._respond(400, {"error": "message_too_long", "message": "message must be 500 characters or fewer."})
            return

        history = body.get("history", [])
        if not isinstance(history, list):
            self._respond(400, {"error": "invalid_history", "message": "history must be an array."})
            return
        history = history[-10:]
        for item in history:
            if (
                not isinstance(item, dict)
                or item.get("role") not in ("user", "assistant")
                or not isinstance(item.get("content"), str)
            ):
                self._respond(400, {"error": "invalid_history", "message": "Each history item must have role and string content."})
                return

        forwarded = self.headers.get("X-Forwarded-For", "unknown")
        ip = forwarded.split(",")[0].strip()
        if not _check_rate_limit(ip):
            self._respond(429, {"error": "rate_limit", "message": "Too many requests. Please wait a moment."})
            return

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            self._respond(500, {"error": "config_error", "message": "Service is not configured."})
            return

        model = os.getenv("CHAT_MODEL", "google/gemini-2.5-flash")
        timeout = int(os.getenv("OPENROUTER_TIMEOUT", "30"))
        # EMBEDDING_MODEL must match the model used in scripts/index_docs.py to produce
        # vectors of the same dimension as doc_chunks.embedding (vector(1536)).
        embedding_model = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
        database_url = os.getenv("DATABASE_URL", "")

        system_prompt = _SYSTEM_PROMPT
        if database_url:
            try:
                with closing(get_connection(database_url)) as conn:
                    chunks = retrieve_doc_chunks(message, conn, api_key, embedding_model)
                    if chunks:
                        context_block = "\n\n".join(
                            f"[{c['source']} / {c['heading']}]\n{c['content']}"
                            for c in chunks
                        )
                        system_prompt = (
                            _SYSTEM_PROMPT
                            + "\n\n---\n\nRELEVANT DOCUMENTATION\n\n"
                            + context_block
                        )
            except Exception:
                pass

        messages = [{"role": "system", "content": system_prompt}]
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": message})

        try:
            resp = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://axiom-aruneemb.vercel.app",
                    "X-Title": "Axiom",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 600,
                    "temperature": 0.4,
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            reply = data["choices"][0]["message"]["content"].strip()
            tokens_used = data.get("usage", {}).get("total_tokens", 0)
            self._respond(200, {"reply": reply, "tokens_used": tokens_used})
        except httpx.HTTPStatusError as e:
            self._respond(500, {"error": "llm_error", "message": f"LLM request failed: {e.response.status_code}"})
        except Exception:
            self._respond(500, {"error": "llm_error", "message": "Failed to generate a response."})

    def _respond(self, status: int, body: dict):
        """Serialise body as JSON and write a complete HTTP response."""
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        """Suppress default BaseHTTPRequestHandler access logging."""
        pass
     
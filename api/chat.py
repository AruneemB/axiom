import json
import os
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_SYSTEM_PROMPT: str | None = None

_rate_limit: dict[str, tuple[int, float]] = {}
_WINDOW_SECS = 60
_MAX_REQUESTS = 30


def _load_system_prompt() -> str:
    global _SYSTEM_PROMPT
    if _SYSTEM_PROMPT is None:
        prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "site_chat_system.txt"
        _SYSTEM_PROMPT = prompt_path.read_text(encoding="utf-8")
    return _SYSTEM_PROMPT


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
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_POST(self):
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

        model = os.getenv("CHAT_MODEL", "google/gemini-flash-1.5")
        timeout = int(os.getenv("OPENROUTER_TIMEOUT", "30"))
        system_prompt = _load_system_prompt()

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
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(payload))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        pass

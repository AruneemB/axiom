# AXIOM-CHAT-AND-ISSUES

> Sequential prompts for completing the Chat and GitHub Issues features.
> The backend libraries, migrations, config, and security validation were built in a prior session. These prompts cover the remaining handler functions, config gaps, dependency additions, and deployment steps.

---

## What Already Exists

The following files were created and are **complete**:

| File | Purpose |
|------|---------|
| `lib/chat.py` | Session management, context retrieval, message storage, OpenRouter chat call, rate limiting, session cleanup |
| `lib/github_client.py` | `create_issue()` via PyGithub, `validate_github_token()`, `format_issue_body()`, `generate_issue_title()` |
| `lib/security_validator.py` | Content validation pipeline (length, profanity, spam, injection, malware), PII detection, sanitization |
| `migrations/006_add_conversations.sql` | `conversation_sessions` and `conversation_messages` tables with indexes |
| `migrations/007_add_github_submissions.sql` | `github_submissions` table with indexes |
| `prompts/chat_system.txt` | System prompt template with paper/idea context placeholders |
| `lib/config.py` (modified) | Config fields for chat settings and GitHub integration added |
| `api/telegram.py` (modified) | Routing for `/chat`, `/context`, `/report` added; library imports wired |

---

## Prompt 01 — Add Chat Model to Config

**Read:** `lib/config.py` and `lib/chat.py` (the `generate_chat_response` function signature).

**Edit this file:**

- `lib/config.py`

**Requirements:**

1. Add a `chat_model` field to the `Config` dataclass, typed as `str`.
2. In `load_config()`, set it from the environment with a cheap default: `os.getenv("CHAT_MODEL", "google/gemini-flash-1.5")`. This model is fast and inexpensive on OpenRouter — ideal for conversational use.
3. Confirm that `generate_chat_response` in `lib/chat.py` accepts a `model` parameter — the handler will pass `cfg.chat_model` to it.

**Verify:**

```bash
python -c "from lib.config import load_config; print('chat_model field ok')"
```

---

## Prompt 02 — Add PyGithub Dependency

**Edit this file:**

- `requirements.txt`

**Requirements:**

1. Add `PyGithub` to `requirements.txt`. This is required by `lib/github_client.py` which imports `from github import Github`.
2. Do not change any existing dependencies.

**Verify:**

```bash
pip install PyGithub
python -c "from github import Github; print('PyGithub ok')"
```

---

## Prompt 03 — Implement `handle_chat`

**Read:** `api/telegram.py`, `lib/chat.py`, `lib/config.py`.

**Edit this file:**

- `api/telegram.py`

**Requirements:**

1. Define `handle_chat(user_id, chat_id, text, conn, cfg)` in `api/telegram.py`. This is the core chat handler.

2. **Guard check** — if `cfg.chat_enabled` is `False`, reply "Chat is currently disabled." and return.

3. **Parse the message** — strip the `/chat` prefix. If the remaining text is empty, send a usage message:
   ```
   Send /chat followed by your message to discuss your latest research idea.
   Example: /chat How would I implement this with tick data?
   ```

4. **Rate limit check** — call `check_rate_limits(user_id, None, conn)`. If blocked, send the error message and return.

5. **Session setup** — call `get_or_create_session(user_id, None, None, conn)`. Wrap in a try/except for `ValueError` (no ideas delivered yet) — if caught, reply "No research ideas available yet. Wait for your first delivery or use /spark." and return.

6. **Fetch context** — call `get_conversation_context(session_id, cfg.chat_context_window, conn)`.

7. **Store the user message** — call `store_message(session_id, "user", user_message, 0, conn)`.

8. **Generate response** — call `generate_chat_response(context, user_message, cfg.chat_model, cfg.openrouter_api_key, cfg.openrouter_timeout)`. Wrap in try/except for `httpx.HTTPStatusError` and generic `Exception` — on error, reply "Sorry, I couldn't generate a response. Please try again." and return.

9. **Store the assistant message** — call `store_message(session_id, "assistant", response_text, tokens_used, conn)`.

10. **Send the response** — call `send_message(chat_id, response_text, cfg.telegram_bot_token)`.

**Verify:**

```bash
python -c "from api.telegram import handle_chat; print('handle_chat ok')"
```

---

## Prompt 04 — Implement `handle_context`

**Read:** `api/telegram.py`, `lib/chat.py`.

**Edit this file:**

- `api/telegram.py`

**Requirements:**

1. Define `handle_context(user_id, chat_id, conn, cfg)` in `api/telegram.py`.

2. **Find active session** — query `conversation_sessions` for the user's most recent active session (`expires_at > NOW()`). If none exists, reply "No active chat session. Start one with /chat." and return.

3. **Fetch context** — call `get_conversation_context(session_id, cfg.chat_context_window, conn)`.

4. **Format and send** — build a message showing:
   ```
   Active Chat Context

   Paper: {title}
   Hypothesis: {hypothesis}
   Method: {method}
   Dataset: {dataset}
   Scores: Novelty {novelty}/10, Feasibility {feasibility}/10
   Messages in session: {count}
   ```
   Send via `send_message`.

**Verify:**

```bash
python -c "from api.telegram import handle_context; print('handle_context ok')"
```

---

## Prompt 05 — Implement `handle_report`

**Read:** `api/telegram.py`, `lib/github_client.py`, `lib/security_validator.py`, `lib/config.py`.

**Edit this file:**

- `api/telegram.py`

**Requirements:**

1. Define `handle_report(user_id, chat_id, text, msg, conn, cfg)` in `api/telegram.py`. This is the GitHub issue submission handler.

2. **Guard check** — if `cfg.github_token` is empty, reply "GitHub integration is not configured." and return.

3. **Parse the description** — strip the `/report` prefix. If empty, send a usage message:
   ```
   Send /report followed by your issue description.
   Example: /report The novelty scores seem inflated for NLP papers
   ```

4. **Daily rate limit** — query `github_submissions` for the user's submissions today. If count >= `cfg.max_github_issues_per_day`, reply "Daily issue limit reached ({limit}/day). Try again tomorrow." and return.

5. **Security validation** — call `validate_issue_content(description)`. If invalid, send the error message and return.

6. **PII check** — call `detect_pii(description)`. If PII detected, reply "Your submission contains personal information ({types}). Please remove it and try again." and return.

7. **Sanitize** — call `sanitize_content(description)`.

8. **AI-powered title generation** — call the OpenRouter API to generate a concise, well-formed issue title from the description. Use `cfg.chat_model` (or `cfg.default_model`) with a short system prompt: "Generate a concise GitHub issue title (under 70 chars) for this user report. Return only the title, nothing else." Fall back to `generate_issue_title(description)` if the API call fails.

9. **Build context** — check for an active chat session for context. Build `user_info` dict with `username`, `user_id`, and `timestamp`. Call `format_issue_body(sanitized_description, context_data, user_info)`.

10. **Create the issue** — call `create_issue(title, body, cfg.github_issue_labels, [], cfg.github_repo_owner, cfg.github_repo_name, cfg.github_token)`. Wrap in try/except for `GithubException` — on error, reply "Failed to create issue. Please try again later." and return.

11. **Record the submission** — insert into `github_submissions` table with `user_id`, `issue_number`, `issue_url`, `title`, `description`, `context_data`, and `validation_flags`.

12. **Confirm to user** — reply with:
    ```
    Issue #{number} created successfully.
    {html_url}
    ```

**Verify:**

```bash
python -c "from api.telegram import handle_report; print('handle_report ok')"
```

---

## Prompt 06 — Run Migrations

**Requirements:**

1. Run migrations `006_add_conversations.sql` and `007_add_github_submissions.sql` against the database.
2. Verify the tables were created:

```bash
psql $DATABASE_URL -c "\dt conversation_sessions"
psql $DATABASE_URL -c "\dt conversation_messages"
psql $DATABASE_URL -c "\dt github_submissions"
```

---

## Prompt 07 — Environment Variables

**Edit this file:**

- `.env.example`

**Requirements:**

1. Add the following variables with comments to `.env.example`:

```env
# Chat feature
CHAT_ENABLED=true
CHAT_MODEL=google/gemini-flash-1.5
CHAT_CONTEXT_WINDOW=10
CHAT_MAX_MESSAGES_PER_SESSION=20
CHAT_MAX_ACTIVE_SESSIONS_PER_USER=5
CHAT_MAX_MESSAGES_PER_HOUR=20
CHAT_SESSION_TIMEOUT_HOURS=2
CHAT_MAX_TOKENS_PER_USER_PER_DAY=50000

# GitHub issue integration
GITHUB_TOKEN=
GITHUB_REPO_OWNER=
GITHUB_REPO_NAME=
GITHUB_ISSUE_LABELS=user-reported,needs-triage
MAX_GITHUB_ISSUES_PER_DAY=3
```

2. Add `CHAT_MODEL` and `GITHUB_TOKEN` to the production environment (Vercel dashboard or equivalent).

---

## Prompt 08 — Tests

**Create these files:**

- `tests/test_chat.py`
- `tests/test_github_client.py`
- `tests/test_security_validator.py`

**Requirements:**

1. `tests/test_chat.py`:
   - `test_check_rate_limits_passes_fresh_user()` — mock DB to return zero counts, verify `(True, "")`.
   - `test_check_rate_limits_blocks_session_limit()` — mock `message_count` at 20, verify blocked.
   - `test_generate_chat_response_builds_correct_payload()` — mock `httpx.Client.post`, verify the messages array includes system prompt, history, and new user message.

2. `tests/test_github_client.py`:
   - `test_generate_issue_title_short_sentence()` — input under 70 chars returns as-is.
   - `test_generate_issue_title_truncates_long()` — input over 70 chars returns 67 chars + "...".
   - `test_format_issue_body_includes_user_info()` — verify output contains username and timestamp.
   - `test_format_issue_body_includes_paper_context()` — verify arXiv link appears when paper_id provided.

3. `tests/test_security_validator.py`:
   - `test_validates_minimum_length()` — 5-char input rejected.
   - `test_validates_maximum_length()` — 6000-char input rejected.
   - `test_detects_sql_injection()` — input with `'; DROP TABLE` rejected.
   - `test_detects_xss()` — input with `<script>` rejected.
   - `test_detects_spam_caps()` — all-caps input rejected.
   - `test_detects_pii_email()` — input with email address returns `["email"]`.
   - `test_sanitize_strips_html()` — `<b>bold</b>` becomes `bold`.
   - `test_passes_valid_content()` — clean, normal text passes validation.

**Verify:**

```bash
pytest tests/test_chat.py tests/test_github_client.py tests/test_security_validator.py -v
```

---

## Post-Completion Checklist

After completing all 8 prompts, verify:

1. **New handler functions exist:**
   ```bash
   python -c "from api.telegram import handle_chat, handle_context, handle_report; print('all handlers ok')"
   ```

2. **Config complete:**
   ```bash
   python -c "from lib.config import load_config; c = load_config(); print(c.chat_model, c.github_token); print('config ok')"
   ```

3. **Full test suite passes:**
   ```bash
   pytest tests/ -v
   ```

4. **Migrations applied:** all three new tables exist in the database.

5. **Environment variables set:** `CHAT_MODEL`, `GITHUB_TOKEN`, `GITHUB_REPO_OWNER`, `GITHUB_REPO_NAME` configured in production.

6. **End-to-end smoke test:**
   - Send `/chat How would I test this hypothesis?` to the bot — expect a contextual response.
   - Send `/context` — expect paper/idea summary.
   - Send `/report The scoring seems biased toward NLP topics` — expect a GitHub issue link.

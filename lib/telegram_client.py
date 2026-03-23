import httpx

TELEGRAM_BASE = "https://api.telegram.org"


def _sanitize(text: str) -> str:
    return text.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")


def send_message(chat_id: int, text: str, bot_token: str, parse_mode: str = None):
    text = _sanitize(text)
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    httpx.post(
        f"{TELEGRAM_BASE}/bot{bot_token}/sendMessage",
        json=payload,
        timeout=10,
    ).raise_for_status()


def send_idea_message(
    chat_id: int,
    idea_id: int,
    title: str,
    url: str,
    idea: dict,
    bot_token: str,
):
    def esc(s: str) -> str:
        for c in r"\_*[]()~`>#+-=|{}.!":
            s = s.replace(c, f"\\{c}")
        return s

    n = idea["novelty_score"]
    f = idea["feasibility_score"]
    score_bar = "\u2588" * n + "\u2591" * (10 - n)

    text = (
        f"*{esc(title)}*\n"
        f"[arxiv]({esc(url)})\n\n"
        f"*Hypothesis*\n{esc(idea['hypothesis'])}\n\n"
        f"*Method*\n{esc(idea['method'])}\n\n"
        f"*Data*\n{esc(idea['dataset'])}\n\n"
        f"*Novelty* {n}/10 \u00b7 *Feasibility* {f}/10\n"
        f"`{score_bar}`"
    )

    inline_keyboard = {
        "inline_keyboard": [[
            {"text": "\ud83d\udc4d Interesting", "callback_data": f"feedback:{idea_id}:1"},
            {"text": "\ud83d\udc4e Skip", "callback_data": f"feedback:{idea_id}:-1"},
            {"text": "\ud83d\udcc4 Paper", "url": url},
        ]]
    }

    text = _sanitize(text)

    httpx.post(
        f"{TELEGRAM_BASE}/bot{bot_token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "MarkdownV2",
            "reply_markup": inline_keyboard,
            "disable_web_page_preview": True,
        },
        timeout=10,
    ).raise_for_status()


def register_webhook(bot_token: str, webhook_url: str, secret: str):
    resp = httpx.post(
        f"{TELEGRAM_BASE}/bot{bot_token}/setWebhook",
        json={
            "url": webhook_url,
            "secret_token": secret,
            "allowed_updates": ["message", "callback_query"],
        },
    )
    resp.raise_for_status()
    return resp.json()

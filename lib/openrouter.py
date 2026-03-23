import json
import httpx
from typing import Optional
from pathlib import Path

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT = (_prompts_dir / "system.txt").read_text().strip()
EXTRACTION_TEMPLATE = (_prompts_dir / "extraction.txt").read_text().strip()
IDEATION_TEMPLATE = (_prompts_dir / "ideation.txt").read_text().strip()


def synthesize_idea(
    title: str,
    abstract: str,
    model: str,
    api_key: str,
) -> tuple[Optional[dict], str]:

    user_prompt = (
        EXTRACTION_TEMPLATE.replace("{title}", title).replace("{abstract}", abstract)
        + "\n\n"
        + IDEATION_TEMPLATE
    )

    response = httpx.post(
        f"{OPENROUTER_BASE}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://axiom.app",
            "X-Title": "Axiom",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 1000,
            "response_format": {"type": "json_object"},
        },
        timeout=30,
    )

    response.raise_for_status()
    raw = response.json()["choices"][0]["message"]["content"]
    # Gemini "thinking" models sometimes emit lone UTF-16 surrogates;
    # re-encode with surrogatepass then decode replacing them.
    content = raw.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")

    try:
        parsed = json.loads(content)
        result = _validate_idea(parsed)
        if result is None:
            keys = list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
            return None, f"validation failed, keys={keys}, raw={content[:300]}"
        return result, ""
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        return None, f"parse error ({type(exc).__name__}): {exc}, raw={content[:300]}"


def _validate_idea(raw: dict) -> Optional[dict]:
    # If LLM returned a list of ideas, pick the highest combined score
    if isinstance(raw.get("ideas"), list):
        ideas = raw["ideas"]
        raw = max(ideas, key=lambda i: i.get("novelty_score", 0) + i.get("feasibility_score", 0))

    required = {"hypothesis", "method", "dataset", "novelty_score", "feasibility_score"}
    if not required.issubset(raw.keys()):
        return None

    if not 1 <= int(raw["novelty_score"]) <= 10:
        return None
    if not 1 <= int(raw["feasibility_score"]) <= 10:
        return None

    return {
        "hypothesis": str(raw["hypothesis"]).strip(),
        "method": str(raw["method"]).strip(),
        "dataset": str(raw["dataset"]).strip(),
        "novelty_score": int(raw["novelty_score"]),
        "feasibility_score": int(raw["feasibility_score"]),
    }

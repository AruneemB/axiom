import json
import httpx
import time
from typing import Optional
from pathlib import Path

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_prompts_dir = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT = (_prompts_dir / "system.txt").read_text().strip()
EXTRACTION_TEMPLATE = (_prompts_dir / "extraction.txt").read_text().strip()
IDEATION_TEMPLATE = (_prompts_dir / "ideation.txt").read_text().strip()
EXPAND_TEMPLATE = (_prompts_dir / "expand.txt").read_text().strip()


def synthesize_idea(
    title: str,
    abstract: str,
    model: str,
    api_key: str,
    fallback_model: Optional[str] = None,
    max_retries: int = 2,
    timeout: int = 60,
) -> tuple[Optional[dict], str]:

    user_prompt = (
        EXTRACTION_TEMPLATE.replace("{title}", title).replace("{abstract}", abstract)
        + "\n\n"
        + IDEATION_TEMPLATE
    )

    last_error = ""
    # Try with primary model
    for attempt in range(max_retries + 1):
        try:
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
                    "temperature": 0.9,
                    "max_tokens": 1000,
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            break
        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            
            # If primary fails and we have a fallback, try the fallback once
            if fallback_model:
                try:
                    response = httpx.post(
                        f"{OPENROUTER_BASE}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "HTTP-Referer": "https://axiom.app",
                            "X-Title": "Axiom",
                        },
                        json={
                            "model": fallback_model,
                            "messages": [
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt},
                            ],
                            "temperature": 0.9,
                            "max_tokens": 1000,
                            "response_format": {"type": "json_object"},
                        },
                        timeout=30, # Shorter timeout for fallback
                    )
                    response.raise_for_status()
                    break # Success with fallback
                except Exception as fe:
                    return None, f"Primary failed ({last_error}) and fallback failed: {str(fe)}"
            
            return None, f"Max retries reached. Last error: {last_error}"
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"

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


def expand_idea(
    title: str,
    abstract: str,
    hypothesis: str,
    method: str,
    dataset: str,
    model: str,
    api_key: str,
    fallback_model: Optional[str] = None,
    max_retries: int = 2,
    timeout: int = 90,
) -> tuple[Optional[dict], str]:

    user_prompt = (
        EXPAND_TEMPLATE
        .replace("{title}", title)
        .replace("{abstract}", abstract)
        .replace("{hypothesis}", hypothesis)
        .replace("{method}", method)
        .replace("{dataset}", dataset)
    )

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
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
                    "max_tokens": 2000,
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout,
            )
            response.raise_for_status()
            break
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_error = str(e)
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue

            if fallback_model:
                try:
                    response = httpx.post(
                        f"{OPENROUTER_BASE}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "HTTP-Referer": "https://axiom.app",
                            "X-Title": "Axiom",
                        },
                        json={
                            "model": fallback_model,
                            "messages": [
                                {"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": user_prompt},
                            ],
                            "temperature": 0.7,
                            "max_tokens": 2000,
                            "response_format": {"type": "json_object"},
                        },
                        timeout=30,
                    )
                    response.raise_for_status()
                    break
                except (httpx.RequestError, httpx.HTTPStatusError) as fe:
                    return None, f"Primary failed ({last_error}) and fallback failed: {str(fe)}"

            return None, f"Max retries reached. Last error: {last_error}"
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"

    raw = response.json()["choices"][0]["message"]["content"]
    content = raw.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="replace")

    try:
        parsed = json.loads(content)
        result = _validate_expand(parsed)
        if result is None:
            keys = list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
            return None, f"validation failed, keys={keys}, raw={content[:300]}"
        return result, ""
    except (json.JSONDecodeError, KeyError, ValueError) as exc:
        return None, f"parse error ({type(exc).__name__}): {exc}, raw={content[:300]}"


def _validate_expand(raw) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    required = {"pseudocode", "statistical_tests", "timeline", "risk_factors"}
    if not required.issubset(raw.keys()):
        return None
    if not isinstance(raw["statistical_tests"], list) or not isinstance(raw["timeline"], list):
        return None

    tests = [
        t for t in raw["statistical_tests"]
        if isinstance(t, dict) and {"test", "rationale", "threshold"}.issubset(t.keys())
    ]
    if not tests:
        return None

    timeline = [
        p for p in raw["timeline"]
        if isinstance(p, dict) and {"phase", "weeks", "tasks"}.issubset(p.keys())
    ]
    if not timeline:
        return None

    return {
        "pseudocode": str(raw["pseudocode"]).strip(),
        "statistical_tests": tests,
        "timeline": timeline,
        "risk_factors": str(raw["risk_factors"]).strip(),
    }


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

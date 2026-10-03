"""Unified LLM client — Bedrock primary, FastRouter OpenAI-compatible fallback.

Bedrock stays primary so the AWS Builder mini-challenge integration is real
(documented AWS service usage). FastRouter guarantees the skill answers today
while the AWS account verification is pending, and as resilience afterwards.

Track which provider answered via the `provider` field in results.
"""
from __future__ import annotations

import json
import logging
import os

import httpx

from . import bedrock_client

log = logging.getLogger("marketpulse.llm")

FR_BASE = os.environ.get("LLM_BASE_URL", "https://api.fastrouter.ai/api/v1")
FR_MODEL = os.environ.get("LLM_MODEL", "anthropic/claude-opus-4.7")
FR_KEY = os.environ.get("LLM_API_KEY", "")

SYSTEM = (
    "You are MarketPulse, a market research analyst inside an Alexa+ skill. "
    "Answer in plain spoken English, concise enough to be read aloud. "
    "Ground every number in the DATA provided; never invent figures. "
    "Currency is Brazilian Real (BRL)."
)


def _fastrouter(messages: list[dict], system: str, max_tokens: int) -> str:
    if not FR_KEY:
        raise RuntimeError("FastRouter API key not configured")
    full = [{"role": "system", "content": system}] + messages
    r = httpx.post(
        f"{FR_BASE}/chat/completions",
        headers={"Authorization": f"Bearer {FR_KEY}", "Content-Type": "application/json"},
        json={"model": FR_MODEL, "messages": full,
              "max_tokens": max_tokens, "temperature": 0.3},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()


def complete(prompt: str, system: str = SYSTEM, max_tokens: int = 1024,
             prefer: str = "bedrock") -> tuple[str, str]:
    """Return (text, provider). `prefer` selects the first provider tried."""
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    order = ["bedrock", "fastrouter"] if prefer == "bedrock" else ["fastrouter", "bedrock"]
    last_err: Exception | None = None
    for provider in order:
        try:
            if provider == "bedrock":
                text = bedrock_client.converse(messages, system=system,
                                               max_tokens=max_tokens)
            else:
                text = _fastrouter([{"role": "user", "content": prompt}],
                                   system, max_tokens)
            return text, provider
        except Exception as e:  # noqa: BLE001
            log.warning("%s failed (%s); trying next", provider, str(e)[:120])
            last_err = e
    raise RuntimeError(f"All LLM providers failed; last error: {last_err}")


def narrate(tool: str, data: dict, max_tokens: int = 220) -> tuple[str, str]:
    """Generate a 1-2 sentence spoken insight for a tool's data payload."""
    prompt = (
        f"TOOL: {tool}\nDATA (JSON):\n{json.dumps(data, default=str)[:3000]}\n\n"
        "In 1-2 short spoken sentences, give the key takeaway a business user "
        "should hear. Name the standout numbers. No preamble."
    )
    return complete(prompt, max_tokens=max_tokens)


def analyst_answer(question: str, data_context: str) -> tuple[str, str]:
    prompt = f"QUESTION: {question}\n\nDATA:\n{data_context}\n\nAnswer in 2-4 spoken sentences."
    # Deep reasoning deserves the strongest model; Bedrock stays as fallback.
    return complete(prompt, max_tokens=1024, prefer="fastrouter")


def narrate_brief(title: str, sections: dict) -> tuple[str, str]:
    body = "\n\n".join(f"## {k}\n{v}" for k, v in sections.items())
    prompt = (f"Write a market intelligence brief titled '{title}'. "
              f"Under 250 words, spoken-friendly.\n\nFINDINGS:\n{body}")
    return complete(prompt, max_tokens=1500, prefer="fastrouter")


def health_check() -> dict:
    try:
        text, provider = complete("Reply with exactly: OK", max_tokens=16)
        return {"ok": True, "provider": provider,
                "bedrock_region": bedrock_client.REGION, "reply": text}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:300]}

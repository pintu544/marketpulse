"""AWS Bedrock client — all LLM reasoning in MarketPulse goes through Bedrock.

Uses the Converse API (bedrock:InvokeModel permission) with the
alexa-bedrock-agent IAM credentials. Model: Claude Haiku 4.5 via the
us-east-1 inference profile, with graceful fallback to Nova Micro.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger("marketpulse.bedrock")

REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
# Inference-profile IDs are required for Anthropic models in us-east-1.
MODEL_CANDIDATES = [
    # Nova Micro works on this account today; Anthropic models need a
    # use-case form submitted in the Bedrock console (see docs/friction-log.md).
    "us.amazon.nova-micro-v1:0",
    "amazon.nova-micro-v1:0",
    os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "anthropic.claude-3-5-haiku-20241022-v1:0",
]

SYSTEM_PROMPT = (
    "You are MarketPulse, a market research analyst inside an Alexa+ skill. "
    "Answer in plain spoken English, concise enough to be read aloud (2-4 sentences "
    "unless the user asked for a full brief). Always ground numbers in the DATA provided; "
    "never invent figures. Currency is Brazilian Real (BRL). If the data is missing, say so."
)


def _client():
    return boto3.client("bedrock-runtime", region_name=REGION)


def converse(messages: list[dict], system: str = SYSTEM_PROMPT,
             max_tokens: int = 1024) -> str:
    """Call Bedrock Converse API, trying model candidates in order."""
    client = _client()
    last_err: Exception | None = None
    seen: set[str] = set()
    for model_id in MODEL_CANDIDATES:
        if model_id in seen or not model_id:
            continue
        seen.add(model_id)
        try:
            resp = client.converse(
                modelId=model_id,
                system=[{"text": system}],
                messages=messages,
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.3},
            )
            return "".join(
                b["text"] for b in resp["output"]["message"]["content"] if "text" in b
            ).strip()
        except ClientError as e:
            last_err = e
            code = e.response.get("Error", {}).get("Code", "")
            log.warning("Bedrock model %s failed (%s), trying next", model_id, code)
            continue
    raise RuntimeError(f"All Bedrock models failed; last error: {last_err}")


def analyst_answer(question: str, data_context: str) -> str:
    """Answer a free-form market question grounded in retrieved data."""
    return converse([{
        "role": "user",
        "content": [{"text": f"QUESTION: {question}\n\nDATA:\n{data_context}"}],
    }])


def narrate_brief(title: str, sections: dict) -> str:
    """Turn structured findings into a spoken-style market brief."""
    body = "\n\n".join(f"## {k}\n{v}" for k, v in sections.items())
    return converse(
        [{
            "role": "user",
            "content": [{"text": f"Write a market intelligence brief titled '{title}'. "
                                  f"Keep it under 250 words, spoken-friendly.\n\nFINDINGS:\n{body}"}],
        }],
        max_tokens=1500,
    )


def health_check() -> dict:
    """Verify Bedrock is reachable; returns model used or error info."""
    try:
        text = converse([{"role": "user",
                          "content": [{"text": "Reply with exactly: OK"}]}], max_tokens=16)
        return {"ok": True, "region": REGION, "reply": text}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "region": REGION, "error": str(e)[:300]}

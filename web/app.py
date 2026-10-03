"""Simulated Alexa+ experience — web host for the MarketPulse MCP server.

An Alexa+ device would call the MCP server's tools to answer voice queries.
This web app simulates that host: it takes a typed/spoken-style question,
routes it to the right MCP tool over Streamable HTTP, and renders the answer
in an Alexa-style voice UI. Runs on $WEB_PORT (default 8766).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from mcp import Client
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

load_dotenv()

MCP_URL = os.environ.get("MCP_URL", "http://127.0.0.1:8765/mcp")
HERE = Path(__file__).resolve().parent

# Category names for fuzzy matching in questions.
CATEGORIES = [
    "health_beauty", "watches_gifts", "bed_bath_table", "sports_leisure",
    "computers_accessories", "furniture_decor", "electronics", "housewares",
    "auto", "toys", "fashion_bags_accessories", "perfumery",
]


def find_category(q: str) -> str | None:
    ql = q.lower().replace(" ", "_")
    for c in CATEGORIES:
        if c in ql or c.replace("_", " ") in q.lower():
            return c
    return None


def route(question: str) -> tuple[str, dict]:
    """Map a natural-language question to (tool_name, args)."""
    q = question.lower()
    cat = find_category(question)
    # "compare X vs Y" / "X versus Y"
    m = re.search(r"compare\s+([\w_ ]+?)\s+(?:vs\.?|versus|and)\s+([\w_ ]+)", q)
    if m:
        a = m.group(1).strip().replace(" ", "_")
        b = m.group(2).strip().replace(" ", "_").rstrip("?")
        return "compare_categories", {"category_a": a, "category_b": b}
    if any(w in q for w in ("brief", "summary report", "market intelligence")):
        return "generate_brief", {"focus": question[:120]}
    if any(w in q for w in ("trend", "growth", "growing", "month over month")):
        return "growth_trends", {"category": cat, "months": 12}
    if any(w in q for w in ("top product", "best seller", "best-seller", "best selling")):
        return "top_products", {"category": cat, "limit": 5}
    if any(w in q for w in ("review", "rating", "rated", "satisfaction")):
        return "review_insights", {"category": cat}
    if any(w in q for w in ("deliver", "shipping", "late", "shipment")):
        return "delivery_impact", {"category": cat, "limit": 8}
    if any(w in q for w in ("revenue", "sales", "earn", "how much")) and cat:
        return "category_revenue", {"category": cat}
    return "ask_analyst", {"question": question}


async def ask(request):
    body = await request.json()
    question = body.get("question", "").strip()
    if not question:
        return JSONResponse({"error": "empty question"}, status_code=400)
    tool, args = route(question)
    # drop None args
    args = {k: v for k, v in args.items() if v is not None}
    try:
        async with Client(MCP_URL) as client:
            result = await client.call_tool(tool, args)
        payload = result.content[0].text if result.content else "{}"
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"raw": payload}
        if getattr(result, "is_error", False):
            return JSONResponse({"tool": tool, "error": data}, status_code=502)
        return JSONResponse({"tool": tool, "args": args, "data": data})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"tool": tool, "error": str(e)[:400]}, status_code=502)


async def index(request):
    return HTMLResponse((HERE / "index.html").read_text())


async def health(request):
    try:
        async with Client(MCP_URL) as client:
            tools = await client.list_tools()
        names = [t.name for t in (tools.tools if hasattr(tools, "tools") else tools[0])]
        return JSONResponse({"mcp": "ok", "tools": names})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"mcp": "down", "error": str(e)[:200]}, status_code=502)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/ask", ask, methods=["POST"]),
    Route("/api/health", health),
])

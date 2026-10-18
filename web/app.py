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
    if any(w in q for w in ("checkout", "place order", "complete purchase", "buy now")):
        return "checkout", {}
    if any(w in q for w in ("cart", "basket")) and not any(w in q for w in ("add", "put")):
        return "view_cart", {}
    m = re.search(r"(?:add|put)\s+(.+?)\s+(?:to|in)\s+(?:cart|basket)", q)
    if m:
        item = m.group(1).strip()
        qm = re.search(r"(\d+)\s+(?:x|units?|pieces?)\b", q)
        qty = int(qm.group(1)) if qm else 1
        # strip quantity words from item name
        item = re.sub(r"^\d+\s+(?:x|units?|pieces?)\s+", "", item).strip()
        return "add_to_cart", {"sku": item, "quantity": qty}
    if any(w in q for w in ("browse", "show products", "catalog", "shop for", "looking for")):
        return "browse_products", {"category": cat, "limit": 6}
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


async def shop(request):
    return HTMLResponse((HERE / "shop.html").read_text())


async def health(request):
    try:
        async with Client(MCP_URL) as client:
            tools = await client.list_tools()
        names = [t.name for t in (tools.tools if hasattr(tools, "tools") else tools[0])]
        return JSONResponse({"mcp": "ok", "tools": names})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"mcp": "down", "error": str(e)[:200]}, status_code=502)


# --- Agentic commerce (PayPal hackathon, T1.3) ---

async def commerce_create_mission(request):
    from marketpulse.commerce.models import create_mission
    from marketpulse.commerce.missions import research_and_propose

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    if not isinstance(body, dict):
        return JSONResponse({"error": "body must be a JSON object"}, status_code=400)

    query = body.get("query", "")
    if not isinstance(query, str):
        return JSONResponse({"error": "query must be a string"}, status_code=400)
    query = query.strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)

    max_budget = body.get("maxBudget")
    if max_budget is not None:
        try:
            max_budget = float(max_budget)
            import math
            if not math.isfinite(max_budget) or max_budget <= 0:
                raise ValueError
        except (ValueError, TypeError):
            return JSONResponse({"error": "maxBudget must be a positive finite number"}, status_code=400)

    mission = create_mission(query=query, max_budget=max_budget)
    # Slice 1: synchronous research → proposal
    research_and_propose(mission)
    return JSONResponse({"missionId": mission.id, "status": mission.status})


async def commerce_get_mission(request):
    from marketpulse.commerce.models import get_mission

    mission_id = request.path_params["id"]
    mission = get_mission(mission_id)
    if mission is None:
        return JSONResponse({"error": "mission not found"}, status_code=404)
    return JSONResponse(mission.to_dict())


async def commerce_confirm_mission(request):
    """The human gate (T2.2): approve or decline the proposal.

    Body: { "confirmed": true } → executes the order (status → executing)
    Body: { "confirmed": false } → marks mission failed cleanly.
    """
    from marketpulse.commerce.models import get_mission
    from marketpulse.commerce.transact import execute_order
    from marketpulse.commerce.guardrails import GuardrailViolation
    from marketpulse.commerce.paypal_client import PayPalError

    mission_id = request.path_params["id"]
    mission = get_mission(mission_id)
    if mission is None:
        return JSONResponse({"error": "mission not found"}, status_code=404)

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    if not isinstance(body, dict) or not isinstance(body.get("confirmed"), bool):
        return JSONResponse(
            {"error": "body must be {\"confirmed\": boolean}"}, status_code=400
        )

    if mission.status != "proposed":
        return JSONResponse(
            {"error": f"mission status is {mission.status!r}, must be 'proposed'"},
            status_code=409,
        )

    if not body["confirmed"]:
        mission.status = "failed"
        mission.log("mission_declined", "human declined the proposal")
        return JSONResponse({"status": "failed"})

    # Human confirmed — execute the order
    try:
        order = execute_order(mission)
    except GuardrailViolation as e:
        mission.status = "failed"
        mission.log("order_blocked", str(e))
        return JSONResponse({"error": str(e)}, status_code=422)
    except PayPalError as e:
        # H1: PayPal failures → 502, mission stays retryable (C1 fix)
        mission.log("order_failed", f"paypal error: {e}")
        return JSONResponse(
            {"error": "payment provider unavailable, safe to retry"},
            status_code=502,
        )
    except KeyError as e:
        # Missing env credentials
        return JSONResponse(
            {"error": "payment not configured"},
            status_code=503,
        )

    return JSONResponse({"status": "executing", "order": order})


async def commerce_catalog(request):
    """T2.4: return the fixture catalog (versioned, stable IDs, fixed prices)."""
    from marketpulse.commerce.missions import load_catalog
    from marketpulse.commerce.constants import SANDBOX_LABEL, ENVIRONMENT

    return JSONResponse({
        "environment": ENVIRONMENT,
        "sandboxLabel": SANDBOX_LABEL,
        "items": load_catalog(),
    })


app = Starlette(routes=[
    Route("/", index),
    Route("/shop", shop),
    Route("/api/ask", ask, methods=["POST"]),
    Route("/api/health", health),
    Route("/api/commerce/mission", commerce_create_mission, methods=["POST"]),
    Route("/api/commerce/mission/{id}", commerce_get_mission),
    Route("/api/commerce/mission/{id}/confirm", commerce_confirm_mission, methods=["POST"]),
    Route("/api/commerce/catalog", commerce_catalog),
])

"""Mission lifecycle: research → proposal.

Slice 1 (T1.3): synchronous research against the fixture catalog.
Slice 2 (T2.1): wired to the MarketPulse research pipeline —
    category-aware ranking with price-grounded insights.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .models import Mission

_CATALOG_PATH = Path(__file__).parent / "fixtures" / "catalog.json"


def load_catalog() -> list[dict]:
    with open(_CATALOG_PATH) as f:
        return json.load(f)["items"]


def _marketpulse_ranked_options(query: str) -> list[dict]:
    """Get ranked product options from the MarketPulse research pipeline.

    Uses the MarketPulse catalog (fictional brands, real price grounding)
    to find category-relevant options for the query. Returns ranked list
    with insight context.

    H2: never throws — a backend failure returns [] and the fixture
    catalog still proposes. Enrichment must not take down mission creation.
    """
    try:
        from marketpulse import tools as mp_tools
    except Exception:
        # ImportError, FileNotFoundError (missing DB), etc. → degrade gracefully
        return []

    try:
        query_lower = query.lower()
        # Map query to MarketPulse categories
        category_hints = {
            "headphone": "electronics",
            "earbud": "electronics",
            "keyboard": "computers_accessories",
            "watch": "watches_gifts",
            "shoe": "sports_leisure",
            "chair": "furniture_decor",
            "perfume": "perfumery",
            "bag": "fashion_bags_accessories",
        }

        matched_category = None
        for hint, cat in category_hints.items():
            if hint in query_lower:
                matched_category = cat
                break

        result = mp_tools.browse_products(category=matched_category, limit=8)
        products = result.get("products", [])
        # Rank by name relevance to query
        query_words = set(query_lower.split())
        ranked = []
        for p in products:
            name_words = set(p.get("name", "").lower().split())
            overlap = len(query_words & name_words)
            ranked.append((overlap, p))
        ranked.sort(key=lambda x: -x[0])
        return [p for _, p in ranked]
    except Exception:
        # H2: backend failure → degrade gracefully
        return []


def research_and_propose(mission: Mission) -> dict | None:
    """Run the research step: find the best item for the mission query.

    T2.1: consults both the fixture catalog (transactable, USD) and the
    MarketPulse research pipeline (category-aware, price-grounded).
    Returns the proposal dict, or None if nothing matches.
    """
    mission.log("research_started", f"query={mission.query!r}")

    # MarketPulse pipeline: get ranked options with insight context
    mp_options = _marketpulse_ranked_options(mission.query)
    if mp_options:
        mission.log(
            "research_insight",
            f"marketpulse ranked {len(mp_options)} options, "
            f"top={mp_options[0].get('name', '?')}",
        )

    catalog = load_catalog()

    # H1: non-finite budgets bypass Decimal comparisons — reject early.
    budget_cap = None
    if mission.max_budget is not None:
        budget_cap = Decimal(str(mission.max_budget))
        if not budget_cap.is_finite() or budget_cap <= 0:
            mission.log("research_complete", f"invalid budget: {mission.max_budget!r}")
            mission.status = "failed"
            return None

    query_words = set(mission.query.lower().split())
    candidates = []
    for item in catalog:
        name_words = set(item["name"].lower().split())
        overlap = query_words & name_words
        if not overlap:
            continue
        price = Decimal(item["price"])
        if budget_cap is not None and price > budget_cap:
            continue
        candidates.append((len(overlap), item))

    if not candidates:
        mission.log("research_complete", "no matching items found")
        mission.status = "failed"
        return None

    # Best = most word overlap, then lowest price
    candidates.sort(key=lambda c: (-c[0], Decimal(c[1]["price"])))
    best = candidates[0][1]

    # T2.1: enrich reason with MarketPulse insight if available.
    # M2: only cite it when the top option is actually query-relevant —
    # otherwise it reads as fabricated reasoning.
    reason = f"Best value match for {mission.query!r} within budget"
    if mp_options:
        top_mp = mp_options[0]
        top_words = set(top_mp.get("name", "").lower().split())
        if query_words & top_words:
            reason += f" (MarketPulse: {top_mp.get('name')} at R${top_mp.get('price_brl')})"

    proposal = {
        "itemId": best["id"],
        "name": best["name"],
        "brand": best["brand"],
        "price": best["price"],
        "currency": mission.currency,
        "reason": reason,
    }
    mission.proposal = proposal
    mission.status = "proposed"
    mission.log("proposal_ready", f"item={best['id']} price={best['price']}")
    return proposal

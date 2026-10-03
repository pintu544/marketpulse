"""MarketPulse tool implementations — pure functions over the Olist dataset.

Each function returns JSON-serializable dicts. server.py registers them
as MCP tools. Bedrock-powered tools ground every answer in retrieved data.
"""
from __future__ import annotations

import json

from . import data, llm_client


def _with_insight(tool_name: str, payload: dict) -> dict:
    """Attach a 1-2 sentence spoken insight from the LLM to a data payload."""
    try:
        insight, provider = llm_client.narrate(tool_name, payload)
        payload["insight"] = insight
        payload["powered_by"] = provider
    except Exception as e:  # noqa: BLE001
        payload["insight"] = None
        payload["powered_by"] = f"llm_unavailable: {str(e)[:120]}"
    return payload


def _money(v: float | None) -> float | None:
    return round(v, 2) if v is not None else None


def category_revenue(category: str, include_insight: bool = True) -> dict:
    """Total revenue, orders and average review score for a product category."""
    row = data.category_summary(category)
    if not row:
        close = data.search_categories(category)
        return {"found": False, "category": category,
                "did_you_mean": close[:5]}
    payload = {
        "found": True,
        "category": row["category_english"],
        "total_revenue_brl": _money(row["total_revenue"]),
        "total_orders": row["total_orders"],
        "avg_review_score": round(row["avg_review"], 2) if row["avg_review"] else None,
        "avg_delivery_days": round(row["avg_delivery_days"], 1) if row["avg_delivery_days"] else None,
    }
    return _with_insight("category_revenue", payload) if include_insight else payload


def growth_trends(category: str | None = None, months: int = 12, include_insight: bool = True) -> dict:
    """Month-by-month revenue and order trend, optionally for one category."""
    rows = data.monthly_trend(category, months)
    rows = sorted(rows, key=lambda r: r["year_month"])
    trend = [{"month": r["year_month"], "revenue_brl": _money(r["revenue"]),
              "orders": r["orders"]} for r in rows]
    direction = None
    if len(trend) >= 2:
        first = sum(r["revenue_brl"] for r in trend[:3]) / 3
        last = sum(r["revenue_brl"] for r in trend[-3:]) / 3
        direction = "up" if last > first * 1.05 else "down" if last < first * 0.95 else "flat"
    payload = {"category": category or "all", "months": trend, "trend_direction": direction}
    return _with_insight("growth_trends", payload) if include_insight else payload


def delivery_impact(category: str | None = None, limit: int = 10, include_insight: bool = True) -> dict:
    """Delivery performance: average days and late-delivery rate per category."""
    rows = data.query(
        "SELECT category_english, avg_delivery_days, late_rate, total_orders "
        "FROM category_summary ORDER BY late_rate DESC LIMIT ?", (limit,))
    out = [{
        "category": r["category_english"],
        "avg_delivery_days": round(r["avg_delivery_days"], 1) if r["avg_delivery_days"] else None,
        "late_delivery_rate": round(r["late_rate"], 3) if r["late_rate"] is not None else None,
        "orders": r["total_orders"],
    } for r in rows]
    if category:
        out = [r for r in out if r["category"].lower() == category.lower()]
    payload = {"categories": out}
    return _with_insight("delivery_impact", payload) if include_insight else payload


def review_insights(category: str | None = None, include_insight: bool = True) -> dict:
    """Review score distribution and per-category averages."""
    dist = data.review_distribution()
    by_cat = data.query(
        "SELECT category_english, avg_review, total_orders FROM category_summary "
        "WHERE avg_review IS NOT NULL ORDER BY avg_review DESC LIMIT 10")
    result: dict = {
        "score_distribution": [
            {"score": r["review_score"], "orders": r["orders"]} for r in dist],
        "best_rated_categories": [
            {"category": r["category_english"],
             "avg_score": round(r["avg_review"], 2), "orders": r["total_orders"]}
            for r in by_cat],
    }
    if category:
        row = data.category_summary(category)
        result["requested_category"] = (
            {"category": row["category_english"],
             "avg_score": round(row["avg_review"], 2)} if row and row["avg_review"] else None)
    return _with_insight("review_insights", result) if include_insight else result


def top_products(category: str | None = None, limit: int = 10, include_insight: bool = True) -> dict:
    """Best-selling products by revenue, optionally within a category."""
    rows = data.top_products(category, limit)
    payload = {"products": [
        {"product_id": r["product_id"],
         "category": r.get("category_english", category),
         "revenue_brl": _money(r["revenue"]), "units_sold": r["units"]}
        for r in rows]}
    return _with_insight("top_products", payload) if include_insight else payload


def compare_categories(category_a: str, category_b: str) -> dict:
    """Head-to-head comparison of two categories: revenue, growth, reviews, delivery."""
    a = data.category_summary(category_a)
    b = data.category_summary(category_b)
    if not a or not b:
        return {"found": False, "detail": "one or both categories not found",
                "tried": [category_a, category_b]}
    def _row(r):
        return {
            "category": r["category_english"],
            "total_revenue_brl": _money(r["total_revenue"]),
            "total_orders": r["total_orders"],
            "avg_review": round(r["avg_review"], 2) if r["avg_review"] else None,
            "avg_delivery_days": round(r["avg_delivery_days"], 1) if r["avg_delivery_days"] else None,
            "late_rate": round(r["late_rate"], 3) if r["late_rate"] is not None else None,
        }
    payload = {"a": _row(a), "b": _row(b),
               "winner_by_revenue": a["category_english"] if a["total_revenue"] >= b["total_revenue"] else b["category_english"]}
    return _with_insight("compare_categories", payload)


def _gather_context(question: str) -> str:
    """Retrieve relevant data slices to ground a free-form question."""
    q = question.lower()
    parts = []
    # Find which known categories are mentioned in the question.
    target = None
    for c in data.categories():
        name = c.lower()
        if name in q or name.replace("_", " ") in q:
            target = c
            break
    top = data.top_categories(8)
    parts.append("TOP CATEGORIES BY REVENUE (BRL): " + json.dumps(
        [{k: (round(v, 2) if isinstance(v, float) else v)
          for k, v in c.items()
          if k in ("category_english", "total_revenue", "total_orders")}
         for c in top]))
    if target:
        parts.append(f"CATEGORY DETAIL ({target}): " + json.dumps(category_revenue(target)))
        parts.append(f"GROWTH ({target}): " + json.dumps(growth_trends(target, 6)))
    if any(w in q for w in ("deliver", "shipping", "late")):
        parts.append("DELIVERY: " + json.dumps(delivery_impact(limit=8)))
    if any(w in q for w in ("review", "rating", "satisf")):
        parts.append("REVIEWS: " + json.dumps(review_insights()))
    if any(w in q for w in ("pay", "installment", "credit")):
        parts.append("PAYMENTS: " + json.dumps(data.payment_mix()))
    if any(w in q for w in ("state", "region", "city", "where")):
        parts.append("TOP STATES: " + json.dumps(data.state_summary(8)))
    if any(w in q for w in ("trend", "growth", "growing", "month")):
        parts.append("OVERALL TREND: " + json.dumps(growth_trends(None, 12)))
    return "\n\n".join(parts)


def ask_analyst(question: str) -> dict:
    """Ask a free-form market question; answered by the LLM grounded in live data."""
    try:
        context = _gather_context(question)
        answer, provider = llm_client.analyst_answer(question, context)
        return {"question": question, "answer": answer, "powered_by": provider}
    except Exception as e:  # noqa: BLE001
        return {"question": question,
                "error": f"LLM unavailable: {str(e)[:200]}",
                "powered_by": "none"}


def generate_brief(focus: str = "overall market") -> dict:
    """Generate a spoken-style market intelligence brief via the LLM."""
    try:
        top = data.top_categories(5)
        trend = growth_trends(None, 12, include_insight=False)
        reviews = review_insights(include_insight=False)
        delivery = delivery_impact(limit=5, include_insight=False)
        sections = {
            "Top categories": json.dumps(top, default=str),
            "12-month trend": json.dumps(trend["months"], default=str),
            "Review landscape": json.dumps(reviews["score_distribution"], default=str),
            "Delivery watch": json.dumps(delivery["categories"], default=str),
        }
        brief, provider = llm_client.narrate_brief(f"MarketPulse brief: {focus}", sections)
        return {"focus": focus, "brief": brief, "powered_by": provider}
    except Exception as e:  # noqa: BLE001
        return {"focus": focus, "error": f"LLM unavailable: {str(e)[:200]}",
                "powered_by": "none"}

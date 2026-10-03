"""Fictional product catalog for the MarketPulse purchasing workflow.

All brands are fictional (trademark-safe for the hackathon). Prices are
derived from real Olist category averages. Product IDs link back to the
top-selling real products per category for grounding.
"""
from __future__ import annotations

from . import data

# Fictional brands per category (brand, product name template).
FICTIONAL = {
    "health_beauty": ("Lumina", "Hydra-Glow Moisturizer"),
    "watches_gifts": ("Tempo", "Heritage Chrono Watch"),
    "bed_bath_table": ("CasaLinho", "Egyptian Cotton Sheet Set"),
    "sports_leisure": ("Velocity", "Pro Trail Running Shoes"),
    "computers_accessories": ("Nexbit", "Wireless Ergo Keyboard"),
    "furniture_decor": ("NordCasa", "Oak Accent Chair"),
    "electronics": ("VoltEdge", "65W GaN Fast Charger"),
    "housewares": ("Cucina", "Cast Iron Skillet 26cm"),
    "toys": ("PlayForge", "STEM Robot Kit"),
    "perfumery": ("Essenza", "Citrus Noir Eau de Parfum"),
    "fashion_bags_accessories": ("Milano", "Leather Tote Bag"),
    "auto": ("RoadPro", "Portable Tire Inflator"),
}


def _avg_price(category: str) -> float:
    rows = data.query(
        "SELECT total_revenue, total_orders FROM category_summary "
        "WHERE lower(category_english)=lower(?)", (category,))
    if rows and rows[0]["total_orders"]:
        return round(rows[0]["total_revenue"] / rows[0]["total_orders"], 2)
    return 99.90


_catalog: list[dict] | None = None


def catalog() -> list[dict]:
    """Build the fictional catalog (cached)."""
    global _catalog
    if _catalog is not None:
        return _catalog
    items = []
    for i, (cat, (brand, name)) in enumerate(FICTIONAL.items(), start=1):
        # Link to a real top product for grounding.
        top = data.top_products(cat, 1)
        real_id = top[0]["product_id"] if top else "n/a"
        items.append({
            "sku": f"MP-{i:03d}",
            "brand": brand,
            "name": name,
            "category": cat,
            "price_brl": _avg_price(cat),
            "real_product_ref": real_id,
            "in_stock": True,
        })
    _catalog = items
    return items


def find(sku_or_name: str) -> dict | None:
    q = sku_or_name.lower()
    for p in catalog():
        if p["sku"].lower() == q or q in p["name"].lower() or q in p["brand"].lower():
            return p
    return None


def browse(category: str | None = None, limit: int = 8) -> list[dict]:
    items = catalog()
    if category:
        items = [p for p in items if p["category"].lower() == category.lower()]
    return items[:limit]

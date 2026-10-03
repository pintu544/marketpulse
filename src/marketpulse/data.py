"""SQLite query layer over the aggregated Olist market data."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "marketpulse.db"
SQL_DUMP = DB_PATH.with_suffix(".sql")


def _ensure_db() -> None:
    """Build the SQLite DB from the shipped SQL dump on first run."""
    if DB_PATH.exists():
        return
    if not SQL_DUMP.exists():
        raise FileNotFoundError(
            f"Missing {DB_PATH} and no {SQL_DUMP} to build it from. "
            "Run: python -m marketpulse.etl --dataset-dir /path/to/olist/csvs")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(SQL_DUMP.read_text())


_ensure_db()


def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def query(sql: str, params: tuple = ()) -> list[dict]:
    with _conn() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]


def categories() -> list[str]:
    return [r["category_english"] for r in query(
        "SELECT category_english FROM category_summary ORDER BY total_revenue DESC")]


def category_summary(category: str) -> dict | None:
    rows = query("SELECT * FROM category_summary WHERE lower(category_english)=lower(?)", (category,))
    return rows[0] if rows else None


def top_categories(limit: int = 10) -> list[dict]:
    return query(
        "SELECT category_english, total_revenue, total_orders, avg_review "
        "FROM category_summary ORDER BY total_revenue DESC LIMIT ?", (limit,))


def monthly_trend(category: str | None = None, months: int = 12) -> list[dict]:
    if category:
        return query(
            "SELECT year_month, revenue, orders FROM monthly_category_revenue "
            "WHERE lower(category_english)=lower(?) ORDER BY year_month DESC LIMIT ?",
            (category, months))
    return query(
        "SELECT year_month, revenue, orders FROM monthly_totals "
        "ORDER BY year_month DESC LIMIT ?", (months,))


def top_products(category: str | None = None, limit: int = 10) -> list[dict]:
    if category:
        return query(
            "SELECT product_id, revenue, units FROM top_products "
            "WHERE lower(category_english)=lower(?) ORDER BY revenue DESC LIMIT ?",
            (category, limit))
    return query(
        "SELECT product_id, category_english, revenue, units FROM top_products "
        "ORDER BY revenue DESC LIMIT ?", (limit,))


def payment_mix() -> list[dict]:
    return query("SELECT * FROM payment_mix")


def state_summary(limit: int = 10) -> list[dict]:
    return query(
        "SELECT customer_state, revenue, orders FROM state_summary LIMIT ?", (limit,))


def review_distribution() -> list[dict]:
    return query("SELECT * FROM review_distribution")


def search_categories(term: str, limit: int = 10) -> list[str]:
    like = f"%{term.lower()}%"
    return [r["category_english"] for r in query(
        "SELECT category_english FROM category_summary "
        "WHERE lower(category_english) LIKE ? ORDER BY total_revenue DESC LIMIT ?",
        (like, limit))]

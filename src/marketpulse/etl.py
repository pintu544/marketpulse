"""ETL: aggregate the public Olist e-commerce dataset into a compact SQLite DB.

Reads the raw Olist CSVs (Kaggle: olistbr/brazilian-ecommerce) and produces
data/marketpulse.db with pre-aggregated tables the MCP tools query.
The raw CSVs (~121MB) are NOT shipped in the repo; judges regenerate with:
    python src/marketpulse/etl.py --dataset-dir /path/to/olist/csvs
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATASET = Path.home() / "workspace/udacity-market-research-agent/dataset"
DEFAULT_OUT = HERE / "data" / "marketpulse.db"


def load(dataset_dir: Path) -> dict[str, pd.DataFrame]:
    d = dataset_dir
    orders = pd.read_csv(d / "olist_orders_dataset.csv")
    items = pd.read_csv(d / "olist_order_items_dataset.csv")
    products = pd.read_csv(d / "olist_products_dataset.csv")
    reviews = pd.read_csv(d / "olist_order_reviews_dataset.csv")
    payments = pd.read_csv(d / "olist_order_payments_dataset.csv")
    customers = pd.read_csv(d / "olist_customers_dataset.csv")
    trans = pd.read_csv(d / "product_category_name_translation.csv")
    return {
        "orders": orders, "items": items, "products": products,
        "reviews": reviews, "payments": payments,
        "customers": customers, "trans": trans,
    }


def build_tables(t: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    orders, items, products = t["orders"], t["items"], t["products"]
    reviews, payments = t["reviews"], t["payments"]
    customers, trans = t["customers"], t["trans"]

    cat_en = dict(zip(trans["product_category_name"], trans["product_category_name_english"]))
    products = products.copy()
    products["category_english"] = products["product_category_name"].map(cat_en).fillna(
        products["product_category_name"]
    )

    # Line-level fact: one row per order item, delivered orders only.
    delivered = orders[orders["order_status"] == "delivered"].copy()
    delivered["order_purchase_timestamp"] = pd.to_datetime(delivered["order_purchase_timestamp"])
    delivered["order_delivered_customer_date"] = pd.to_datetime(
        delivered["order_delivered_customer_date"], errors="coerce"
    )
    delivered["order_estimated_delivery_date"] = pd.to_datetime(
        delivered["order_estimated_delivery_date"], errors="coerce"
    )
    fact = items.merge(
        delivered[["order_id", "order_purchase_timestamp",
                   "order_delivered_customer_date", "order_estimated_delivery_date",
                   "customer_id"]],
        on="order_id", how="inner",
    )
    fact = fact.merge(products[["product_id", "category_english"]], on="product_id", how="left")
    fact["category_english"] = fact["category_english"].fillna("unknown")
    fact["revenue"] = fact["price"]
    fact["year_month"] = fact["order_purchase_timestamp"].dt.strftime("%Y-%m")
    fact["delivery_days"] = (
        fact["order_delivered_customer_date"] - fact["order_purchase_timestamp"]
    ).dt.total_seconds() / 86400
    fact["late_days"] = (
        fact["order_delivered_customer_date"] - fact["order_estimated_delivery_date"]
    ).dt.total_seconds() / 86400

    # Reviews per order (dedupe to one score per order).
    rev = reviews.sort_values("review_creation_date").drop_duplicates("order_id", keep="last")
    fact = fact.merge(rev[["order_id", "review_score"]], on="order_id", how="left")

    tables: dict[str, pd.DataFrame] = {}

    tables["monthly_category_revenue"] = (
        fact.groupby(["year_month", "category_english"], as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"),
             items=("order_id", "size"))
        .sort_values(["year_month", "revenue"], ascending=[True, False])
    )

    tables["category_summary"] = (
        fact.groupby("category_english", as_index=False)
        .agg(total_revenue=("revenue", "sum"), total_orders=("order_id", "nunique"),
             avg_review=("review_score", "mean"), avg_delivery_days=("delivery_days", "mean"),
             late_rate=("late_days", lambda s: (s > 0).mean()))
        .sort_values("total_revenue", ascending=False)
    )

    tables["monthly_totals"] = (
        fact.groupby("year_month", as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
        .sort_values("year_month")
    )

    tables["top_products"] = (
        fact.groupby(["product_id", "category_english"], as_index=False)
        .agg(revenue=("revenue", "sum"), units=("order_id", "size"))
        .sort_values("revenue", ascending=False)
        .head(500)
    )

    tables["payment_mix"] = (
        payments.groupby("payment_type", as_index=False)
        .agg(transactions=("order_id", "size"), value=("payment_value", "sum"))
        .sort_values("value", ascending=False)
    )

    cust_state = customers[["customer_id", "customer_state"]].drop_duplicates("customer_id")
    fact_state = fact.merge(cust_state, on="customer_id", how="left")
    tables["state_summary"] = (
        fact_state.groupby("customer_state", as_index=False)
        .agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
        .sort_values("revenue", ascending=False)
        .head(30)
    )

    tables["review_distribution"] = (
        fact.dropna(subset=["review_score"])
        .groupby("review_score", as_index=False)
        .agg(orders=("order_id", "nunique"))
        .sort_values("review_score")
    )

    return tables


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    print(f"Loading CSVs from {args.dataset_dir} ...")
    t = load(args.dataset_dir)
    print("Aggregating ...")
    tables = build_tables(t)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()
    with sqlite3.connect(args.out) as con:
        for name, df in tables.items():
            df.to_sql(name, con, index=False)
            print(f"  {name}: {len(df):,} rows")
    size_mb = args.out.stat().st_size / 1e6
    print(f"Wrote {args.out} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()

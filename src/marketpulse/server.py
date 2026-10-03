"""MarketPulse MCP server — Alexa+ track, Build/Ship/Shape hackathon.

Self-hosted MCP server (spec 2025-11-25) over Streamable HTTP.
Run:  python -m marketpulse.server   (serves POST /mcp on $MCP_PORT)
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from mcp.server import MCPServer

load_dotenv()

from . import tools  # noqa: E402

mcp = MCPServer("MarketPulse")


@mcp.tool()
def category_revenue(category: str) -> dict:
    """Get total revenue (BRL), order count and average review for a product category."""
    return tools.category_revenue(category)


@mcp.tool()
def growth_trends(category: str | None = None, months: int = 12) -> dict:
    """Month-by-month revenue and order trends, optionally for one category."""
    return tools.growth_trends(category, months)


@mcp.tool()
def delivery_impact(category: str | None = None, limit: int = 10) -> dict:
    """Delivery performance: average days and late-delivery rate per category."""
    return tools.delivery_impact(category, limit)


@mcp.tool()
def review_insights(category: str | None = None) -> dict:
    """Review score distribution and best-rated categories."""
    return tools.review_insights(category)


@mcp.tool()
def top_products(category: str | None = None, limit: int = 10) -> dict:
    """Best-selling products by revenue, optionally within a category."""
    return tools.top_products(category, limit)


@mcp.tool()
def compare_categories(category_a: str, category_b: str) -> dict:
    """Head-to-head comparison of two product categories with a verdict."""
    return tools.compare_categories(category_a, category_b)


@mcp.tool()
def ask_analyst(question: str) -> dict:
    """Ask a free-form market research question; answered by Amazon Bedrock grounded in live data."""
    return tools.ask_analyst(question)


@mcp.tool()
def generate_brief(focus: str = "overall market") -> dict:
    """Generate a spoken-style market intelligence brief via Amazon Bedrock."""
    return tools.generate_brief(focus)


def main() -> None:
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8765"))
    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )


if __name__ == "__main__":
    main()

"""PayPal agentic commerce module — sandbox Orders v2 via raw REST (httpx).

Added 2026-10-13 for the PayPal AI Hackathon 2026 entry.
All transactions are SANDBOX (test money only). The Client Secret stays
server-side (env var), never in the frontend or repo.
"""
from .paypal_client import PayPalClient
from .guardrails import check_budget, new_idempotency_key, GuardrailViolation
from .models import create_mission, get_mission, Mission
from .missions import research_and_propose, load_catalog
from .transact import execute_order
from .constants import SANDBOX_LABEL, SANDBOX_BADGE, ENVIRONMENT

__all__ = [
    "PayPalClient",
    "check_budget",
    "new_idempotency_key",
    "GuardrailViolation",
    "create_mission",
    "get_mission",
    "Mission",
    "research_and_propose",
    "load_catalog",
    "execute_order",
    "SANDBOX_LABEL",
    "SANDBOX_BADGE",
    "ENVIRONMENT",
]

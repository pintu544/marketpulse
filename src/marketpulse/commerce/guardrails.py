"""Spend guardrails for agentic commerce — enforced in code, not prompts.

Rules:
- No budget stated -> research only, never transact.
- Transaction amount above the mission budget -> refuse.
- Every create-order carries a unique idempotency key (safe retries).
"""
from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation


class GuardrailViolation(Exception):
    pass


def new_idempotency_key() -> str:
    return str(uuid.uuid4())


def check_budget(amount: str, currency: str, max_budget: str | None) -> None:
    """Raise GuardrailViolation if the transaction must not proceed."""
    if max_budget is None:
        raise GuardrailViolation(
            "no budget stated — research only, refusing to transact"
        )
    try:
        amt = Decimal(amount)
        cap = Decimal(max_budget)
    except InvalidOperation:
        raise GuardrailViolation(f"invalid amount/budget: {amount!r}/{max_budget!r}")
    # H1: reject non-finite values — Decimal('Infinity') makes every
    # `price > cap` comparison False, silently disabling the guardrail.
    if not amt.is_finite() or not cap.is_finite():
        raise GuardrailViolation(
            f"non-finite amount/budget: {amount!r}/{max_budget!r}"
        )
    if amt <= 0:
        raise GuardrailViolation(f"non-positive amount: {amount!r}")
    if amt > cap:
        raise GuardrailViolation(
            f"amount {amt} {currency} exceeds mission budget {cap} {currency}"
        )

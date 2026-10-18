"""Transaction execution with guardrails enforced.

Every order creation goes through `execute_order` — budget is checked
*at transaction time* (not just at research time), and every call
carries an idempotency key.
"""
from __future__ import annotations

import threading

from .guardrails import GuardrailViolation, check_budget, new_idempotency_key
from .models import Mission
from .paypal_client import PayPalClient, PayPalError

# C2: per-mission locks prevent concurrent execute_order races.
_mission_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock_for(mission_id: str) -> threading.Lock:
    with _locks_lock:
        if mission_id not in _mission_locks:
            _mission_locks[mission_id] = threading.Lock()
        return _mission_locks[mission_id]


def execute_order(
    mission: Mission,
    client: PayPalClient | None = None,
) -> dict:
    """Create a PayPal order for the mission's proposal.

    Idempotent at the mission level: calling twice returns the first
    order instead of creating a duplicate (H2). Thread-safe (C2).

    On PayPal failure (C1): the mission keeps its idempotency key but
    NO partial order dict — a retry reuses the same key, and the
    mission stays in 'proposed' so the human can retry.

    Raises:
        GuardrailViolation: if budget check fails, mission has no proposal,
            or mission is not in "proposed" status.
        PayPalError: if the PayPal API call fails.
    """
    # C2: serialize per mission
    with _lock_for(mission.id):
        return _execute_order_inner(mission, client)


def _execute_order_inner(
    mission: Mission,
    client: PayPalClient | None,
) -> dict:
    # C1: check for a COMPLETED order first (has paypalOrderId).
    # A failed attempt leaves no partial dict — only the idempotency key.
    if mission.order is not None and mission.order.get("paypalOrderId"):
        mission.log("order_reused", f"paypalOrderId={mission.order['paypalOrderId']}")
        return mission.order

    # M5: only transact from the proposed state
    if mission.status != "proposed":
        raise GuardrailViolation(
            f"mission status is {mission.status!r}, must be 'proposed' to transact"
        )

    if mission.proposal is None:
        raise GuardrailViolation("no proposal — cannot transact")

    proposal = mission.proposal
    # Transaction-time budget enforcement (T1.4): re-check even though
    # research already filtered. Defense in depth.
    check_budget(
        amount=proposal["price"],
        currency=proposal.get("currency", "USD"),
        max_budget=str(mission.max_budget) if mission.max_budget is not None else None,
    )

    client = client or PayPalClient()
    # C1: reuse the stored idempotency key on retry, don't mint a new one.
    # Stored separately from mission.order so a failure leaves no partial dict.
    idempotency_key = getattr(mission, "_idempotency_key", None)
    if not idempotency_key:
        idempotency_key = new_idempotency_key()
        mission._idempotency_key = idempotency_key

    mission.log(
        "order_creating",
        f"item={proposal['itemId']} amount={proposal['price']} "
        f"idempotency={idempotency_key[:8]}...",
    )

    try:
        order = client.create_order(
            amount=proposal["price"],
            currency=proposal.get("currency", "USD"),
            idempotency_key=idempotency_key,
            description=f"[SANDBOX] {proposal['name']}",
        )
    except PayPalError:
        # C1: leave NO partial order dict. Mission stays 'proposed' with
        # the idempotency key preserved for a safe retry.
        mission.log("order_failed", "paypal call failed, safe to retry")
        raise

    mission.order = {
        "paypalOrderId": order["id"],
        "status": order.get("status", "CREATED"),
        "amount": proposal["price"],
        "currency": proposal.get("currency", "USD"),
        "idempotencyKey": idempotency_key,
        "approveLink": PayPalClient.approve_link(order),
    }
    mission.status = "executing"
    mission.log("order_created", f"paypalOrderId={order['id']}")
    return mission.order

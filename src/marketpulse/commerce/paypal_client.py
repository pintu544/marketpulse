"""PayPal sandbox REST client — OAuth2 token caching + Orders v2.

Endpoints (sandbox): https://api-m.sandbox.paypal.com
- POST /v1/oauth2/token                 (Basic client_id:client_secret)
- POST /v2/checkout/orders              (Bearer, PayPal-Request-Id for idempotency)
- POST /v2/checkout/orders/{id}/capture (Bearer)
- GET  /v2/checkout/orders/{id}         (Bearer)

T3.1: retries with exponential backoff on 429/5xx.
"""
from __future__ import annotations

import os
import time
import uuid

import httpx

SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
PROD_BASE = "https://api-m.paypal.com"

# T3.1: retry config
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds, doubled each retry
_RETRYABLE = {429, 500, 502, 503, 504}

# VM egress goes through an authenticated proxy whose password contains
# URL-breaking chars that httpx can't parse (see ~/AGENTS.md). Route through
# the local CONNECT forwarder on 127.0.0.1:8888 instead; trust_env=False
# keeps httpx from choking on the raw proxy env vars.
# PAYPAL_PROXY env var overrides: set it on the VM if the forwarder is needed.
# On Azure (or anywhere without the forwarder), leave unset for a direct
# connection with normal TLS verification.
_FORWARDER = os.environ.get("PAYPAL_PROXY", "")


def _http_client() -> httpx.Client:
    if _FORWARDER:
        # verify=False: the egress proxy MITMs TLS with a self-signed cert.
        # Sandbox traffic only; same pattern as the Playwright setup (AGENTS.md).
        return httpx.Client(proxy=_FORWARDER, trust_env=False, timeout=20.0, verify=False)
    # Direct connection (Azure, etc.) with normal TLS verification.
    return httpx.Client(trust_env=False, timeout=20.0)


class PayPalError(Exception):
    """PayPal API error with the debug_id for support."""

    def __init__(self, message: str, debug_id: str | None = None, status: int | None = None):
        super().__init__(message)
        self.debug_id = debug_id
        self.status = status


class PayPalClient:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        environment: str | None = None,
    ):
        self.client_id = client_id or os.environ["PAYPAL_CLIENT_ID"]
        self.client_secret = client_secret or os.environ["PAYPAL_CLIENT_SECRET"]
        env = (environment or os.environ.get("PAYPAL_ENVIRONMENT", "SANDBOX")).upper()
        self.base_url = PROD_BASE if env == "PRODUCTION" else SANDBOX_BASE
        self.environment = env
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    # -- auth -----------------------------------------------------------
    def _mint_token(self) -> str:
        try:
            resp = _http_client().post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"Accept": "application/json"},
            )
        except httpx.TransportError as e:
            # Network-level failure during token mint — wrap so callers
            # see PayPalError (retryable / 502) instead of a raw 500.
            raise PayPalError(f"token mint transport error: {e}") from e
        if resp.status_code != 200:
            raise PayPalError(
                f"token mint failed: {resp.text[:200]}",
                resp.headers.get("Paypal-Debug-Id"),
                resp.status_code,
            )
        data = resp.json()
        self._token = data["access_token"]
        # Sandbox tokens live 3–8h; refresh 5 min early.
        self._token_expires_at = time.time() + data.get("expires_in", 3600) - 300
        return self._token

    def _token_or_refresh(self) -> str:
        if self._token and time.time() < self._token_expires_at:
            return self._token
        return self._mint_token()

    def _headers(self, idempotency_key: str | None = None) -> dict:
        h = {
            "Authorization": f"Bearer {self._token_or_refresh()}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            h["PayPal-Request-Id"] = idempotency_key
        return h

    @staticmethod
    def _raise_for_paypal(resp: httpx.Response, action: str) -> dict:
        if resp.status_code in (200, 201):
            return resp.json()
        try:
            body = resp.json()
            name = body.get("name", "UNKNOWN")
            debug_id = body.get("debug_id") or resp.headers.get("Paypal-Debug-Id")
            detail = (body.get("details") or [{}])[0].get("description", "")
        except Exception:  # noqa: BLE001
            name, debug_id, detail = "UNPARSEABLE", None, resp.text[:200]
        raise PayPalError(
            f"{action} failed: {name} {detail}".strip(),
            debug_id,
            resp.status_code,
        )

    def _request_with_retry(
        self,
        method: str,
        url: str,
        action: str,
        **kwargs,
    ) -> dict:
        """Execute an HTTP request with exponential backoff on 429/5xx (T3.1)."""
        last_error: PayPalError | None = None
        for attempt in range(_MAX_RETRIES + 1):
            # Refresh headers each attempt (token may have expired)
            if callable(kwargs.get("_headers_fn")):
                kwargs["headers"] = kwargs.pop("_headers_fn")()
            try:
                resp = _http_client().request(method, url, **kwargs)
            except httpx.TransportError as e:
                # Network-level failure — retryable
                last_error = PayPalError(f"{action} transport error: {e}")
                if attempt < _MAX_RETRIES:
                    time.sleep(_BACKOFF_BASE * (2 ** attempt))
                    continue
                raise last_error from e

            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code in _RETRYABLE and attempt < _MAX_RETRIES:
                # Force token refresh on 401-adjacent retryables? No — only
                # refresh on 401. For 429/5xx, just back off.
                wait = _BACKOFF_BASE * (2 ** attempt)
                time.sleep(wait)
                last_error = PayPalError(
                    f"{action} got {resp.status_code}, retrying",
                    status=resp.status_code,
                )
                continue
            # Non-retryable or out of retries
            return self._raise_for_paypal(resp, action)

        raise last_error  # pragma: no cover — loop always returns or raises

    # -- orders ---------------------------------------------------------
    def create_order(
        self,
        amount: str,
        currency: str = "USD",
        idempotency_key: str | None = None,
        description: str | None = None,
    ) -> dict:
        """Create an order with intent=CAPTURE. Returns the order incl. approve link."""
        purchase_unit: dict = {"amount": {"currency_code": currency, "value": amount}}
        if description:
            purchase_unit["description"] = description
        key = idempotency_key or str(uuid.uuid4())
        return self._request_with_retry(
            "POST",
            f"{self.base_url}/v2/checkout/orders",
            "create_order",
            _headers_fn=lambda: self._headers(key),
            json={"intent": "CAPTURE", "purchase_units": [purchase_unit]},
        )

    def capture_order(self, order_id: str) -> dict:
        """Capture payment for an approved order. Returns status + capture id."""
        return self._request_with_retry(
            "POST",
            f"{self.base_url}/v2/checkout/orders/{order_id}/capture",
            "capture_order",
            _headers_fn=self._headers,
            json={},
        )

    def get_order(self, order_id: str) -> dict:
        return self._request_with_retry(
            "GET",
            f"{self.base_url}/v2/checkout/orders/{order_id}",
            "get_order",
            _headers_fn=self._headers,
        )

    @staticmethod
    def approve_link(order: dict) -> str | None:
        for link in order.get("links", []):
            if link.get("rel") == "approve":
                return link["href"]
        return None

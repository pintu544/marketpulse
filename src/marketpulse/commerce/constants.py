"""Shared constants for agentic commerce.

All transactions are SANDBOX (test money only). These labels must appear
anywhere money is mentioned in the UI or API responses.
"""
from __future__ import annotations

# Displayed on every screen/endpoint where money appears.
SANDBOX_LABEL = "[SANDBOX — test money only]"

# Short version for tight UI spots.
SANDBOX_BADGE = "SANDBOX"

# Environment marker for API responses.
ENVIRONMENT = "sandbox"

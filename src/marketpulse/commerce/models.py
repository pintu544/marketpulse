"""Mission/Order/AuditLog models for agentic commerce.

In-memory store for Slice 1 (T1.3). A persistent DB can replace
the _MISSIONS dict later without changing the API contract.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field


def _now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class AuditEntry:
    action: str
    detail: str
    at: float = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {"action": self.action, "detail": self.detail, "at": self.at}


@dataclass
class Mission:
    id: str
    query: str
    max_budget: float | None
    currency: str = "USD"
    status: str = "researching"  # researching → proposed → confirmed/failed → executing → done
    proposal: dict | None = None
    order: dict | None = None
    audit_log: list[AuditEntry] = field(default_factory=list)
    created_at: float = field(default_factory=_now)

    def log(self, action: str, detail: str) -> None:
        self.audit_log.append(AuditEntry(action=action, detail=detail))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "query": self.query,
            "maxBudget": self.max_budget,
            "currency": self.currency,
            "status": self.status,
            "proposal": self.proposal,
            "order": self.order,
            "auditLog": [e.to_dict() for e in self.audit_log],
            "createdAt": self.created_at,
        }


# In-memory mission store (Slice 1). Key: mission id.
# Capped to prevent unauthenticated memory exhaustion (M4).
_MAX_MISSIONS = 1000
_MISSIONS: dict[str, Mission] = {}


def create_mission(query: str, max_budget: float | None = None) -> Mission:
    if len(_MISSIONS) >= _MAX_MISSIONS:
        # Evict the oldest mission (simple FIFO for the demo)
        oldest = min(_MISSIONS.values(), key=lambda m: m.created_at)
        del _MISSIONS[oldest.id]
    mission = Mission(id=new_id(), query=query, max_budget=max_budget)
    mission.log("mission_created", f"query={query!r} maxBudget={max_budget}")
    _MISSIONS[mission.id] = mission
    return mission


def get_mission(mission_id: str) -> Mission | None:
    return _MISSIONS.get(mission_id)

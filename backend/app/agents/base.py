from datetime import datetime, timezone
from typing import Any

from app.models.state import AgentEvent, KYCState


def log_event(state: KYCState, agent: str, action: str, details: dict[str, Any] | None = None) -> None:
    state.audit_log.append(
        AgentEvent(
            agent=agent,
            action=action,
            timestamp=datetime.now(timezone.utc).isoformat(),
            details=details or {},
        )
    )


def state_to_dict(state: KYCState) -> dict[str, Any]:
    return state.model_dump()

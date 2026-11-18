import time
import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingAction:
    token: str
    user_id: int
    tool_name: str
    arguments: dict[str, Any]
    created_at: float
    expires_at: float


class HITLStore:
    """Almacén en memoria con expiración TTL para confirmaciones Human-in-the-Loop (HU-16)."""

    def __init__(self) -> None:
        self._items: dict[str, PendingAction] = {}

    def _purge_expired(self, now: float) -> None:
        expired = [k for k, v in self._items.items() if now > v.expires_at]
        for k in expired:
            del self._items[k]

    def create_pending(
        self,
        *,
        user_id: int,
        tool_name: str,
        arguments: dict[str, Any],
        ttl_seconds: int = 240,
        now: float | None = None,
    ) -> PendingAction:
        current = now if now is not None else time.monotonic()
        self._purge_expired(current)
        token = uuid.uuid4().hex[:12]
        action = PendingAction(
            token=token,
            user_id=user_id,
            tool_name=tool_name,
            arguments=dict(arguments),
            created_at=current,
            expires_at=current + ttl_seconds,
        )
        self._items[token] = action
        return action

    def pop_pending(
        self,
        *,
        token: str,
        user_id: int,
        now: float | None = None,
    ) -> tuple[PendingAction | None, str]:
        current = now if now is not None else time.monotonic()
        action = self._items.get(token)
        if action is None:
            return None, "NOT_FOUND"
        if action.user_id != user_id:
            return None, "FORBIDDEN"
        del self._items[token]
        if current > action.expires_at:
            return None, "EXPIRED"
        return action, "OK"

    def clear(self) -> None:
        self._items.clear()


hitl_store = HITLStore()


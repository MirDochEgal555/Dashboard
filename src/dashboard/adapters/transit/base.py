from __future__ import annotations

from typing import Protocol

from ...domain.models import Departure


class TransitAdapterError(RuntimeError):
    """Raised when transit departures cannot be loaded from a provider."""


class TransitAdapter(Protocol):
    def resolve_stop(self, stop_query: str) -> tuple[str, str]:
        """Resolve a human-readable stop query to a provider stop ID and display name."""

    def get_departures(
        self,
        stop_id: str,
        *,
        horizon_minutes: int = 60,
        limit: int = 8,
    ) -> list[Departure]:
        """Return normalized departures for a provider stop ID."""

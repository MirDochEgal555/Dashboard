from __future__ import annotations

from datetime import date
from typing import Protocol

from ...domain.models import CalendarEvent


class CalendarAdapterError(RuntimeError):
    """Raised when calendar events cannot be loaded from a provider."""


class CalendarAdapter(Protocol):
    def get_events_for_day(self, target_date: date) -> list[CalendarEvent]:
        """Return normalized events that overlap the requested local day."""

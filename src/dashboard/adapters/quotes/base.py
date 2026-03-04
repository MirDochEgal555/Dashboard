from __future__ import annotations

from typing import Protocol

from ...domain.models import OnThisDayItem, Quote


class QuoteAdapterError(RuntimeError):
    """Raised when a quote cannot be loaded from a provider."""


class OnThisDayAdapterError(RuntimeError):
    """Raised when on-this-day entries cannot be loaded from a provider."""


class QuoteAdapter(Protocol):
    def get_quote(self) -> Quote:
        """Return a normalized quote."""


class OnThisDayAdapter(Protocol):
    def get_entries(self, *, month: int, day: int, max_items: int = 5) -> list[OnThisDayItem]:
        """Return normalized on-this-day entries for the given month/day."""

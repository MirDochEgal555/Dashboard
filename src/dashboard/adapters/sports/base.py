from __future__ import annotations

from typing import Protocol

from ...domain.models import SportsResult


class SportsAdapterError(RuntimeError):
    """Raised when sports scores cannot be loaded from a provider."""


class SportsAdapter(Protocol):
    def get_scores(self, *, max_items: int = 6) -> list[SportsResult]:
        """Return normalized sports scores and upcoming fixtures."""

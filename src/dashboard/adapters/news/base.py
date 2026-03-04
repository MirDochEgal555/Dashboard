from __future__ import annotations

from typing import Protocol

from ...domain.models import Headline


class NewsAdapterError(RuntimeError):
    """Raised when headlines cannot be loaded from a provider."""


class NewsAdapter(Protocol):
    def get_headlines(self, *, max_items: int = 8) -> list[Headline]:
        """Return normalized news headlines from one or more feeds."""

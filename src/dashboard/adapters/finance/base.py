from __future__ import annotations

from typing import Protocol

from ...domain.models import FinanceQuote


class FinanceAdapterError(RuntimeError):
    """Raised when finance quotes cannot be loaded from a provider."""


class FinanceAdapter(Protocol):
    def get_quotes(self, *, max_items: int = 8) -> list[FinanceQuote]:
        """Return normalized stocks/crypto quotes."""

from __future__ import annotations

from typing import Protocol

from ...domain.models import PhotoItem


class PhotosAdapterError(RuntimeError):
    """Raised when photos cannot be loaded from the configured source."""


class PhotosAdapter(Protocol):
    def get_photos(self) -> list[PhotoItem]:
        """Return local photos normalized for dashboard rendering."""

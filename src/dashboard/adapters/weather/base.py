from __future__ import annotations

from typing import Protocol

from ...domain.models import WeatherSnapshot


class WeatherAdapterError(RuntimeError):
    """Raised when a weather provider request cannot be completed."""


class WeatherAdapter(Protocol):
    def get_weather(self, lat: float, lon: float, *, days: int = 5) -> WeatherSnapshot:
        """Fetch normalized weather data for the provided coordinates."""

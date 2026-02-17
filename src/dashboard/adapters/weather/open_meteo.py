from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...domain.models import DailyForecast, WeatherSnapshot
from .base import WeatherAdapterError

OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
DEFAULT_TIMEOUT_SECONDS = 10

WEATHER_CODE_LABELS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snowfall",
    73: "Moderate snowfall",
    75: "Heavy snowfall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def _coerce_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherAdapterError(f"Invalid numeric value for {field_name}") from exc


def _coerce_int(value: Any, *, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise WeatherAdapterError(f"Invalid integer value for {field_name}") from exc


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def _weather_label(code: int) -> str:
    return WEATHER_CODE_LABELS.get(code, f"Code {code}")


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "rpi-dashboard/0.1"})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise WeatherAdapterError("Failed to fetch weather data from Open-Meteo") from exc

    if not isinstance(payload, dict):
        raise WeatherAdapterError("Unexpected Open-Meteo response shape")
    return payload


class OpenMeteoWeatherAdapter:
    def __init__(
        self,
        *,
        units: Literal["metric", "imperial"] = "metric",
        timezone_name: str = "auto",
    ) -> None:
        self._units = units
        self._timezone_name = timezone_name

    def get_weather(self, lat: float, lon: float, *, days: int = 5) -> WeatherSnapshot:
        forecast_days = min(max(days, 1), 10)
        params = {
            "latitude": f"{lat:.5f}",
            "longitude": f"{lon:.5f}",
            "current": "temperature_2m,weather_code",
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max"
            ),
            "timezone": self._timezone_name,
            "forecast_days": str(forecast_days),
        }
        if self._units == "imperial":
            params["temperature_unit"] = "fahrenheit"

        url = f"{OPEN_METEO_FORECAST_URL}?{urlencode(params)}"
        payload = _fetch_json(url)
        current = payload.get("current")
        daily_data = payload.get("daily")

        if not isinstance(current, dict) or not isinstance(daily_data, dict):
            raise WeatherAdapterError("Open-Meteo response did not include required fields")

        temp = _coerce_float(current.get("temperature_2m"), field_name="current.temperature_2m")
        weather_code = _coerce_int(current.get("weather_code"), field_name="current.weather_code")
        daily = self._parse_daily_forecast(daily_data)

        return WeatherSnapshot(
            temp=temp,
            condition=_weather_label(weather_code),
            daily=daily,
            updated_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def _parse_daily_forecast(daily_data: dict[str, Any]) -> list[DailyForecast]:
        dates = daily_data.get("time")
        min_temps = daily_data.get("temperature_2m_min")
        max_temps = daily_data.get("temperature_2m_max")
        weather_codes = daily_data.get("weather_code")
        precip_probs = daily_data.get("precipitation_probability_max")

        values = (dates, min_temps, max_temps, weather_codes)
        if not all(isinstance(v, list) for v in values):
            raise WeatherAdapterError("Open-Meteo daily forecast payload was incomplete")

        precip_list = precip_probs if isinstance(precip_probs, list) else [None] * len(dates)
        count = min(len(dates), len(min_temps), len(max_temps), len(weather_codes), len(precip_list))

        daily_forecast: list[DailyForecast] = []
        for index in range(count):
            raw_date = dates[index]
            try:
                forecast_date = date.fromisoformat(str(raw_date))
            except ValueError as exc:
                raise WeatherAdapterError("Open-Meteo daily forecast date was invalid") from exc

            min_temp = _coerce_float(min_temps[index], field_name="daily.temperature_2m_min")
            max_temp = _coerce_float(max_temps[index], field_name="daily.temperature_2m_max")
            weather_code = _coerce_int(weather_codes[index], field_name="daily.weather_code")
            precip_prob = _coerce_optional_int(precip_list[index])

            daily_forecast.append(
                DailyForecast(
                    date=forecast_date,
                    min_temp=min_temp,
                    max_temp=max_temp,
                    precip_prob=precip_prob,
                    condition=_weather_label(weather_code),
                )
            )
        return daily_forecast

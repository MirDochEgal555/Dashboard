from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..settings import AppSettings
from ..storage.cache import get_cache_payload, set_cache_entry

LOCATION_CACHE_KEY = "location.current"
LOCATION_CACHE_TTL_SECONDS = 24 * 60 * 60

IP_GEOLOCATION_URL = "https://ipapi.co/json/"
OPEN_METEO_GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
DEFAULT_TIMEOUT_SECONDS = 10


class LocationResolutionError(RuntimeError):
    """Raised when location cannot be resolved from auto and fallback methods."""


def _fetch_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "rpi-dashboard/0.1"})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}
    return payload


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_label(city: str | None, country: str | None, *, fallback: str) -> str:
    city_text = (city or "").strip()
    country_text = (country or "").strip()
    if city_text and country_text:
        return f"{city_text}, {country_text}"
    if city_text:
        return city_text
    if country_text:
        return country_text
    return fallback


def _cached_location(settings: AppSettings) -> tuple[float, float, str] | None:
    payload = get_cache_payload(settings.db_path, LOCATION_CACHE_KEY, allow_stale=False)
    if not isinstance(payload, dict):
        return None

    lat = _coerce_float(payload.get("lat"))
    lon = _coerce_float(payload.get("lon"))
    label = payload.get("label")
    if lat is None or lon is None or not isinstance(label, str) or not label.strip():
        return None
    return lat, lon, label


def _set_cached_location(
    settings: AppSettings,
    *,
    lat: float,
    lon: float,
    label: str,
    source: str,
) -> None:
    set_cache_entry(
        settings.db_path,
        LOCATION_CACHE_KEY,
        {
            "lat": lat,
            "lon": lon,
            "label": label,
            "source": source,
        },
        ttl_seconds=LOCATION_CACHE_TTL_SECONDS,
    )


def _location_from_ip() -> tuple[float, float, str] | None:
    payload = _fetch_json(IP_GEOLOCATION_URL)
    lat = _coerce_float(payload.get("latitude"))
    lon = _coerce_float(payload.get("longitude"))
    if lat is None or lon is None:
        return None
    label = _normalize_label(
        payload.get("city"),
        payload.get("country_name"),
        fallback="Current location",
    )
    return lat, lon, label


def _location_from_fallback_city(city_query: str) -> tuple[float, float, str] | None:
    query = city_query.strip()
    if not query:
        return None

    params = urlencode(
        {
            "name": query,
            "count": 1,
            "language": "en",
            "format": "json",
        }
    )
    payload = _fetch_json(f"{OPEN_METEO_GEOCODING_URL}?{params}")
    results = payload.get("results")
    if not isinstance(results, list) or not results:
        return None

    result = results[0]
    if not isinstance(result, dict):
        return None

    lat = _coerce_float(result.get("latitude"))
    lon = _coerce_float(result.get("longitude"))
    if lat is None or lon is None:
        return None

    label = _normalize_label(
        result.get("name"),
        result.get("country_code"),
        fallback=query,
    )
    return lat, lon, label


def get_location(settings: AppSettings) -> tuple[float, float, str]:
    cached = _cached_location(settings)
    if cached is not None:
        return cached

    mode = settings.yaml.location.mode
    if mode == "auto":
        detected = _location_from_ip()
        if detected is not None:
            lat, lon, label = detected
            _set_cached_location(settings, lat=lat, lon=lon, label=label, source="ip")
            return lat, lon, label

    fallback = _location_from_fallback_city(settings.yaml.location.fallback_city)
    if fallback is not None:
        lat, lon, label = fallback
        _set_cached_location(settings, lat=lat, lon=lon, label=label, source="fallback_city")
        return lat, lon, label

    raise LocationResolutionError("Unable to resolve location from IP or fallback city")

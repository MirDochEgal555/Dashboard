from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from ...domain.models import Departure
from .base import TransitAdapterError

DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_BASE_URL = "https://v6.db.transport.rest"
DEFAULT_FALLBACK_BASE_URLS: tuple[str, ...] = ()
DEFAULT_USER_AGENT = "rpi-dashboard/0.1"
MAX_ATTEMPTS_PER_ENDPOINT = 2


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return None


def _coerce_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(round(float(value)))
        except (TypeError, ValueError):
            return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _fetch_json(url: str, *, user_agent: str) -> dict[str, Any] | list[Any]:
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise TransitAdapterError(f"Failed to fetch transit data from {url}") from exc

    if not isinstance(payload, (dict, list)):
        raise TransitAdapterError("Unexpected transport.rest response shape")
    return payload


def _normalize_base_url(raw_url: str) -> str:
    normalized_url = raw_url.strip().rstrip("/")
    parsed = urlparse(normalized_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise TransitAdapterError(f"Invalid transport.rest base URL: {raw_url}")
    return normalized_url


def _build_status(
    payload: dict[str, Any],
    *,
    planned_time: datetime,
    realtime_time: datetime | None,
) -> str:
    if bool(payload.get("cancelled")):
        return "Cancelled"

    delay_seconds = _coerce_optional_int(payload.get("delay"))
    if delay_seconds is None and realtime_time is not None:
        delay_seconds = int((realtime_time - planned_time).total_seconds())

    if delay_seconds is None:
        return "Scheduled"

    delay_minutes = int(round(delay_seconds / 60))
    if delay_minutes > 0:
        return f"Delayed +{delay_minutes}m"
    if delay_minutes < 0:
        return f"Early {abs(delay_minutes)}m"
    return "On time"


class TransportRestTransitAdapter:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        fallback_base_urls: tuple[str, ...] = DEFAULT_FALLBACK_BASE_URLS,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        primary_base_url = _normalize_base_url(base_url)
        fallback_urls = [_normalize_base_url(url) for url in fallback_base_urls]
        self._base_urls = list(dict.fromkeys([primary_base_url, *fallback_urls]))
        self._user_agent = user_agent.strip() or DEFAULT_USER_AGENT

    def resolve_stop(self, stop_query: str) -> tuple[str, str]:
        query = stop_query.strip()
        if not query:
            raise TransitAdapterError("Transit stop query must not be empty")

        payload = self._request(
            "/locations",
            {
                "query": query,
                "results": "8",
                "stops": "true",
                "addresses": "false",
                "poi": "false",
                "subStops": "false",
                "language": "en",
            },
        )

        if not isinstance(payload, list):
            raise TransitAdapterError("Unexpected stop lookup response from transport.rest")

        for item in payload:
            if not isinstance(item, dict):
                continue

            stop_id = _first_non_empty(item.get("id"))
            station = item.get("station")
            station_name = station.get("name") if isinstance(station, dict) else None
            stop_name = _first_non_empty(item.get("name"), station_name, query)
            if stop_id and stop_name:
                return stop_id, stop_name

        raise TransitAdapterError(f"No stop found for query '{query}'")

    def get_departures(
        self,
        stop_id: str,
        *,
        horizon_minutes: int = 60,
        limit: int = 8,
    ) -> list[Departure]:
        resolved_stop_id = stop_id.strip()
        if not resolved_stop_id:
            raise TransitAdapterError("Transit stop id must not be empty")

        duration = min(max(int(horizon_minutes), 5), 180)
        max_rows = min(max(int(limit), 1), 30)
        encoded_stop_id = quote(resolved_stop_id, safe="")
        payload = self._request(
            f"/stops/{encoded_stop_id}/departures",
            {
                "duration": str(duration),
                "remarks": "false",
                "linesOfStops": "false",
                "subStops": "false",
                "language": "en",
            },
        )

        if isinstance(payload, dict):
            departures_payload = payload.get("departures")
        elif isinstance(payload, list):
            departures_payload = payload
        else:
            departures_payload = None

        if not isinstance(departures_payload, list):
            raise TransitAdapterError("Unexpected departures response from transport.rest")

        departures: list[Departure] = []
        for item in departures_payload:
            departure = self._parse_departure(item)
            if departure is not None:
                departures.append(departure)

        departures.sort(
            key=lambda departure: (
                departure.realtime_time or departure.planned_time,
                departure.line.lower(),
                departure.destination.lower(),
            )
        )
        return departures[:max_rows]

    def _request(
        self,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | list[Any]:
        normalized_path = path if path.startswith("/") else f"/{path}"
        errors: list[str] = []
        for base_url in self._base_urls:
            url = f"{base_url}{normalized_path}"
            if params:
                url = f"{url}?{urlencode(params)}"
            last_error: str | None = None
            for attempt in range(1, MAX_ATTEMPTS_PER_ENDPOINT + 1):
                try:
                    return _fetch_json(url, user_agent=self._user_agent)
                except TransitAdapterError as exc:
                    last_error = str(exc)
                    if attempt < MAX_ATTEMPTS_PER_ENDPOINT:
                        time.sleep(0.35 * attempt)
                        continue
            if last_error is not None:
                errors.append(last_error)

        error_preview = "; ".join(errors) if errors else "no endpoints attempted"
        raise TransitAdapterError(
            f"Transit request failed for all configured endpoints: {error_preview}"
        )

    @staticmethod
    def _parse_departure(payload: Any) -> Departure | None:
        if not isinstance(payload, dict):
            return None

        line_payload = payload.get("line")
        line_name = None
        if isinstance(line_payload, dict):
            line_name = _first_non_empty(
                line_payload.get("name"),
                line_payload.get("fahrtNr"),
                line_payload.get("productName"),
                line_payload.get("id"),
            )
        line_name = line_name or _first_non_empty(payload.get("lineName"), payload.get("line")) or "?"

        destination = _first_non_empty(payload.get("direction"))
        destination_payload = payload.get("destination")
        if destination is None and isinstance(destination_payload, dict):
            destination = _first_non_empty(destination_payload.get("name"))
        destination = destination or _first_non_empty(destination_payload) or "Unknown destination"

        planned_time = _parse_iso_datetime(payload.get("plannedWhen")) or _parse_iso_datetime(
            payload.get("when")
        )
        if planned_time is None:
            return None

        realtime_time = _parse_iso_datetime(payload.get("when"))
        platform = _first_non_empty(payload.get("platform"), payload.get("plannedPlatform"))
        status = _build_status(payload, planned_time=planned_time, realtime_time=realtime_time)

        return Departure(
            line=line_name,
            destination=destination,
            planned_time=planned_time,
            realtime_time=realtime_time,
            platform=platform,
            status=status,
        )

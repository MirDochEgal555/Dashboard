from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ...domain.models import OnThisDayItem
from .base import OnThisDayAdapterError

DEFAULT_USER_AGENT = "rpi-dashboard/0.1"
DEFAULT_TIMEOUT_SECONDS = 12
WIKIMEDIA_EVENTS_URL = "https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/events/{month}/{day}"
WIKIPEDIA_EVENTS_URL = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}"


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _first_page_url(page_payload: dict[str, Any]) -> str | None:
    content_urls = page_payload.get("content_urls")
    if not isinstance(content_urls, dict):
        return None
    desktop = content_urls.get("desktop")
    if not isinstance(desktop, dict):
        return None
    url = _clean_text(desktop.get("page"))
    return url


def _fetch_json(url: str, *, user_agent: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OnThisDayAdapterError(f"Failed to fetch on-this-day entries from {url}") from exc

    if not isinstance(payload, dict):
        raise OnThisDayAdapterError("On-this-day provider returned unexpected payload shape")
    return payload


class WikipediaOnThisDayAdapter:
    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._user_agent = user_agent.strip() or DEFAULT_USER_AGENT

    def get_entries(self, *, month: int, day: int, max_items: int = 5) -> list[OnThisDayItem]:
        safe_month = min(max(int(month), 1), 12)
        safe_day = min(max(int(day), 1), 31)
        limit = max(1, int(max_items))

        payload: dict[str, Any] | None = None
        errors: list[str] = []
        for template in (WIKIMEDIA_EVENTS_URL, WIKIPEDIA_EVENTS_URL):
            url = template.format(month=safe_month, day=safe_day)
            try:
                payload = _fetch_json(url, user_agent=self._user_agent)
                break
            except OnThisDayAdapterError as exc:
                errors.append(str(exc))
                continue

        if payload is None:
            raise OnThisDayAdapterError("; ".join(errors))

        events_payload = payload.get("events")
        if not isinstance(events_payload, list):
            raise OnThisDayAdapterError("On-this-day payload did not contain events")

        entries: list[OnThisDayItem] = []
        seen_texts: set[str] = set()
        for item in events_payload:
            if not isinstance(item, dict):
                continue

            text = _clean_text(item.get("text"))
            if text is None:
                continue

            normalized_text_key = text.casefold()
            if normalized_text_key in seen_texts:
                continue
            seen_texts.add(normalized_text_key)

            year = _coerce_int(item.get("year"))
            page_title: str | None = None
            page_url: str | None = None
            pages_payload = item.get("pages")
            if isinstance(pages_payload, list) and pages_payload:
                first_page = pages_payload[0]
                if isinstance(first_page, dict):
                    page_title = _clean_text(first_page.get("title"))
                    page_url = _first_page_url(first_page)

            entries.append(
                OnThisDayItem(
                    year=year,
                    text=text,
                    source=page_title or "Wikipedia",
                    url=page_url,
                )
            )
            if len(entries) >= limit:
                break

        return entries

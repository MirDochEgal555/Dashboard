from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ...domain.models import Quote
from .base import QuoteAdapterError

DEFAULT_USER_AGENT = "rpi-dashboard/0.1"
DEFAULT_TIMEOUT_SECONDS = 12
QUOTABLE_RANDOM_URL = "https://api.quotable.io/random"
ZENQUOTES_RANDOM_URL = "https://zenquotes.io/api/random"


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _fetch_json(url: str, *, user_agent: str) -> dict[str, Any] | list[Any]:
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
        raise QuoteAdapterError(f"Failed to fetch quote from {url}") from exc

    if not isinstance(payload, (dict, list)):
        raise QuoteAdapterError(f"Quote provider returned unexpected payload shape: {url}")
    return payload


class QuotableQuoteAdapter:
    def __init__(self, *, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self._user_agent = user_agent.strip() or DEFAULT_USER_AGENT

    def get_quote(self) -> Quote:
        providers = (
            self._fetch_quotable,
            self._fetch_zenquotes,
        )
        errors: list[str] = []
        for provider in providers:
            try:
                return provider()
            except QuoteAdapterError as exc:
                errors.append(str(exc))
                continue
        raise QuoteAdapterError("; ".join(errors))

    def _fetch_quotable(self) -> Quote:
        payload = _fetch_json(QUOTABLE_RANDOM_URL, user_agent=self._user_agent)
        if not isinstance(payload, dict):
            raise QuoteAdapterError("Quotable returned unexpected payload shape")

        text = _clean_text(payload.get("content"))
        author = _clean_text(payload.get("author")) or "Unknown"
        if text is None:
            raise QuoteAdapterError("Quotable quote was missing content")

        return Quote(
            text=text,
            author=author,
            source="Quotable",
        )

    def _fetch_zenquotes(self) -> Quote:
        payload = _fetch_json(ZENQUOTES_RANDOM_URL, user_agent=self._user_agent)
        if not isinstance(payload, list) or not payload:
            raise QuoteAdapterError("ZenQuotes returned unexpected payload shape")

        first_item = payload[0]
        if not isinstance(first_item, dict):
            raise QuoteAdapterError("ZenQuotes returned unexpected payload shape")

        text = _clean_text(first_item.get("q"))
        author = _clean_text(first_item.get("a")) or "Unknown"
        if text is None:
            raise QuoteAdapterError("ZenQuotes quote was missing content")

        return Quote(
            text=text,
            author=author,
            source="ZenQuotes",
        )

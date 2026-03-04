from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...domain.models import FinanceQuote
from .base import FinanceAdapterError

STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
STOOQ_HISTORY_URL = "https://stooq.com/q/d/l/"
COINGECKO_SIMPLE_PRICE_URL = "https://api.coingecko.com/api/v3/simple/price"
DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_USER_AGENT = "rpi-dashboard/0.1"

CRYPTO_TICKER_MAP = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
    "cardano": "ADA",
    "ripple": "XRP",
    "dogecoin": "DOGE",
    "litecoin": "LTC",
    "polkadot": "DOT",
}


def _normalize_stock_symbols(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in values:
        if not isinstance(raw_value, str):
            raise FinanceAdapterError("finance stock symbol entries must be strings")
        text = raw_value.strip().upper()
        if not text:
            continue
        normalized.append(text)
    return tuple(dict.fromkeys(normalized))


def _normalize_crypto_ids(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in values:
        if not isinstance(raw_value, str):
            raise FinanceAdapterError("finance crypto id entries must be strings")
        text = raw_value.strip().lower()
        if not text:
            continue
        normalized.append(text)
    return tuple(dict.fromkeys(normalized))


def _coerce_float(value: Any, *, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise FinanceAdapterError(f"Invalid numeric value for {field_name}") from exc


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetch_text(url: str, *, user_agent: str) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            return response.read().decode("utf-8")
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError) as exc:
        raise FinanceAdapterError(f"Failed to fetch finance data from {url}") from exc


def _fetch_json(url: str, *, user_agent: str) -> dict[str, Any]:
    raw_text = _fetch_text(url, user_agent=user_agent)
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise FinanceAdapterError(f"Finance provider returned invalid JSON: {url}") from exc
    if not isinstance(payload, dict):
        raise FinanceAdapterError(f"Finance provider returned unexpected payload shape: {url}")
    return payload


def _stooq_query_symbol(configured_symbol: str) -> str:
    lower_value = configured_symbol.lower()
    if "." in lower_value:
        return lower_value
    return f"{lower_value}.us"


def _parse_stooq_timestamp(date_value: str, time_value: str, *, fallback: datetime) -> datetime:
    date_text = date_value.strip()
    time_text = time_value.strip()
    if not date_text or date_text == "N/D":
        return fallback
    if not time_text or time_text == "N/D":
        time_text = "00:00:00"

    try:
        parsed = datetime.fromisoformat(f"{date_text} {time_text}")
    except ValueError:
        return fallback
    return parsed.replace(tzinfo=timezone.utc)


def _parse_stooq_price(value: str, *, field_name: str) -> float | None:
    text = value.strip()
    if not text or text == "N/D":
        return None
    return _coerce_float(text, field_name=field_name)


def _compute_percent_change(*, open_value: float | None, close_value: float | None) -> float | None:
    if open_value is None or close_value is None or open_value == 0:
        return None
    return ((close_value - open_value) / open_value) * 100.0


def _compute_24h_change(*, previous_close: float | None, latest_close: float | None) -> float | None:
    if previous_close is None or latest_close is None or previous_close == 0:
        return None
    return ((latest_close - previous_close) / previous_close) * 100.0


def _parse_stooq_history_close_values(payload_text: str) -> list[float]:
    rows = list(csv.DictReader(io.StringIO(payload_text)))
    closes: list[float] = []
    for row in rows:
        close_value = _parse_stooq_price(str(row.get("Close", "")), field_name="stooq.history.close")
        if close_value is None:
            continue
        closes.append(close_value)
    return closes


def _crypto_display_symbol(crypto_id: str) -> str:
    mapped = CRYPTO_TICKER_MAP.get(crypto_id)
    if mapped is not None:
        return mapped
    return crypto_id.replace("-", " ").upper()


class StooqCoinGeckoFinanceAdapter:
    def __init__(
        self,
        *,
        stock_symbols: Iterable[str],
        crypto_ids: Iterable[str],
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._stock_symbols = _normalize_stock_symbols(stock_symbols)
        self._crypto_ids = _normalize_crypto_ids(crypto_ids)
        self._user_agent = user_agent.strip() or DEFAULT_USER_AGENT

    def get_quotes(self, *, max_items: int = 8) -> list[FinanceQuote]:
        limit = max(1, int(max_items))
        if not self._stock_symbols and not self._crypto_ids:
            return []

        combined: list[FinanceQuote] = []
        errors: list[str] = []

        if self._stock_symbols:
            try:
                combined.extend(self._get_stooq_quotes())
            except FinanceAdapterError as exc:
                errors.append(str(exc))

        if self._crypto_ids:
            try:
                combined.extend(self._get_coingecko_quotes())
            except FinanceAdapterError as exc:
                errors.append(str(exc))

        if not combined and errors:
            raise FinanceAdapterError("; ".join(errors))

        deduped: list[FinanceQuote] = []
        seen_symbols: set[str] = set()
        for quote in combined:
            normalized_symbol = quote.symbol.casefold()
            if normalized_symbol in seen_symbols:
                continue
            seen_symbols.add(normalized_symbol)
            deduped.append(quote)

        return deduped[:limit]

    def _get_stooq_quotes(self) -> list[FinanceQuote]:
        quotes: list[FinanceQuote] = []
        errors: list[str] = []

        for stock_symbol in self._stock_symbols:
            query_symbol = _stooq_query_symbol(stock_symbol)
            params = {
                "s": query_symbol,
                "f": "sd2t2ohlcv",
                "h": "",
                "e": "csv",
            }
            url = f"{STOOQ_QUOTE_URL}?{urlencode(params)}"
            try:
                payload_text = _fetch_text(url, user_agent=self._user_agent)
                rows = list(csv.DictReader(io.StringIO(payload_text)))
            except FinanceAdapterError as exc:
                errors.append(f"{stock_symbol}: {exc}")
                continue

            if not rows:
                errors.append(f"{stock_symbol}: empty Stooq response")
                continue

            row = rows[0]
            close_value = _parse_stooq_price(str(row.get("Close", "")), field_name="stooq.close")
            if close_value is None:
                errors.append(f"{stock_symbol}: no close value returned")
                continue

            open_value = _parse_stooq_price(str(row.get("Open", "")), field_name="stooq.open")
            previous_close: float | None = None
            history_url = f"{STOOQ_HISTORY_URL}?{urlencode({'s': query_symbol, 'i': 'd'})}"
            try:
                history_payload_text = _fetch_text(history_url, user_agent=self._user_agent)
                close_history = _parse_stooq_history_close_values(history_payload_text)
                if len(close_history) >= 2:
                    previous_close = close_history[-2]
            except FinanceAdapterError:
                previous_close = None

            timestamp = _parse_stooq_timestamp(
                str(row.get("Date", "")),
                str(row.get("Time", "")),
                fallback=datetime.now(timezone.utc),
            )
            quotes.append(
                FinanceQuote(
                    symbol=stock_symbol,
                    price=close_value,
                    change=(
                        _compute_24h_change(previous_close=previous_close, latest_close=close_value)
                        if previous_close is not None
                        else _compute_percent_change(open_value=open_value, close_value=close_value)
                    ),
                    updated_at=timestamp,
                )
            )

        if not quotes and errors:
            raise FinanceAdapterError("Stooq quotes failed: " + "; ".join(errors))
        return quotes

    def _get_coingecko_quotes(self) -> list[FinanceQuote]:
        ids_param = ",".join(self._crypto_ids)
        url = f"{COINGECKO_SIMPLE_PRICE_URL}?{urlencode({'ids': ids_param, 'vs_currencies': 'usd', 'include_24hr_change': 'true', 'include_last_updated_at': 'true'})}"
        payload = _fetch_json(url, user_agent=self._user_agent)

        quotes: list[FinanceQuote] = []
        for crypto_id in self._crypto_ids:
            item = payload.get(crypto_id)
            if not isinstance(item, dict):
                continue

            try:
                price = _coerce_float(item.get("usd"), field_name=f"coingecko.{crypto_id}.usd")
            except FinanceAdapterError:
                continue

            change = _coerce_optional_float(item.get("usd_24h_change"))
            updated_ts = item.get("last_updated_at")
            updated_at = datetime.now(timezone.utc)
            if isinstance(updated_ts, (int, float)) and updated_ts > 0:
                updated_at = datetime.fromtimestamp(updated_ts, tz=timezone.utc)

            quotes.append(
                FinanceQuote(
                    symbol=_crypto_display_symbol(crypto_id),
                    price=price,
                    change=change,
                    updated_at=updated_at,
                )
            )

        return quotes

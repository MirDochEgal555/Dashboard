from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ...domain.models import SportsResult
from .base import SportsAdapterError

THESPORTSDB_API_BASE = "https://www.thesportsdb.com/api/v1/json"
DEFAULT_API_KEY = "3"
DEFAULT_TIMEOUT_SECONDS = 12
DEFAULT_USER_AGENT = "rpi-dashboard/0.1"
PAST_EVENTS_ENDPOINT = "eventspastleague.php"
NEXT_EVENTS_ENDPOINT = "eventsnextleague.php"

LEAGUE_ID_ALIASES = {
    "nfl": "4391",
    "national football league": "4391",
    "bundesliga": "4331",
    "german bundesliga": "4331",
    "1 bundesliga": "4331",
    "1 bundesliga germany": "4331",
    "premier league": "4328",
    "english premier league": "4328",
    "la liga": "4335",
    "spanish la liga": "4335",
    "serie a": "4332",
    "italian serie a": "4332",
    "ligue 1": "4334",
    "french ligue 1": "4334",
    "uefa champions league": "4480",
    "champions league": "4480",
    "uefa europa league": "4481",
    "mls": "4346",
}

LIVE_STATUS_MARKERS = ("live", "in play", "in progress", "half", "extra time", "pen")
FINAL_STATUS_MARKERS = ("final", "finished", "full time", "ft")
POSTPONED_STATUS_MARKERS = ("postponed", "cancelled", "canceled", "abandoned")


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


def _normalize_lookup_key(value: str) -> str:
    normalized = "".join(character if character.isalnum() else " " for character in value.casefold())
    return " ".join(normalized.split())


def _normalize_api_key(value: str) -> str:
    key = value.strip()
    if not key:
        raise SportsAdapterError("sports api key must not be empty")
    return key


def _normalize_sport(value: str) -> str:
    sport = value.strip()
    if not sport:
        raise SportsAdapterError("sports sport must not be empty")
    return sport


def _normalize_league_names(values: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw_value in values:
        if not isinstance(raw_value, str):
            raise SportsAdapterError("sports league entries must be strings")
        league = raw_value.strip()
        if not league:
            continue
        normalized.append(league)
    return tuple(dict.fromkeys(normalized))


def _normalize_datetime(value: str | None) -> datetime | None:
    if value is None:
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


def _build_api_url(
    *,
    api_key: str,
    endpoint: str,
    params: dict[str, str] | None = None,
) -> str:
    encoded_api_key = quote(api_key, safe="")
    if params:
        return f"{THESPORTSDB_API_BASE}/{encoded_api_key}/{endpoint}?{urlencode(params)}"
    return f"{THESPORTSDB_API_BASE}/{encoded_api_key}/{endpoint}"


def _fetch_json(url: str, *, user_agent: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SportsAdapterError(f"Failed to fetch sports data from {url}") from exc

    if not isinstance(payload, dict):
        raise SportsAdapterError("Sports provider returned unexpected payload shape")
    return payload


def _status_bucket(status: str) -> str:
    normalized = status.casefold()
    if any(marker in normalized for marker in LIVE_STATUS_MARKERS):
        return "live"
    if any(marker in normalized for marker in FINAL_STATUS_MARKERS):
        return "final"
    if any(marker in normalized for marker in POSTPONED_STATUS_MARKERS):
        return "postponed"
    return "scheduled"


def _result_sort_key(result: SportsResult) -> tuple[int, float]:
    bucket = _status_bucket(result.status)
    start_ts = result.start_time.timestamp()
    if bucket == "live":
        return (0, start_ts)
    if bucket == "scheduled":
        return (1, start_ts)
    return (2, -start_ts)


def _parse_event_start(payload: dict[str, Any], *, fallback: datetime) -> datetime:
    timestamp_value = _clean_text(payload.get("strTimestamp"))
    parsed_timestamp = _normalize_datetime(timestamp_value)
    if parsed_timestamp is not None:
        return parsed_timestamp

    date_value = _clean_text(payload.get("dateEvent")) or _clean_text(payload.get("dateEventLocal"))
    time_value = _clean_text(payload.get("strTime")) or _clean_text(payload.get("strTimeLocal")) or "00:00:00"
    if date_value is None:
        return fallback

    dt_text = f"{date_value}T{time_value}"
    parsed_dt = _normalize_datetime(dt_text)
    if parsed_dt is None:
        parsed_dt = _normalize_datetime(date_value)
    if parsed_dt is None:
        return fallback
    return parsed_dt


def _parse_score(payload: dict[str, Any]) -> str:
    home_score = _coerce_int(payload.get("intHomeScore"))
    away_score = _coerce_int(payload.get("intAwayScore"))
    if home_score is None or away_score is None:
        return "--"
    return f"{home_score}-{away_score}"


def _derive_status(
    payload: dict[str, Any],
    *,
    start_time: datetime,
    has_score: bool,
    now_utc: datetime,
) -> str:
    raw_status = _clean_text(payload.get("strStatus"))
    if raw_status is not None and raw_status.casefold() not in {"ns", "not started"}:
        return raw_status

    if has_score and start_time <= now_utc:
        return "Final"

    if start_time > now_utc:
        return "Scheduled"

    if (now_utc - start_time).total_seconds() <= 3 * 3600:
        return "Live"

    return "Scheduled"


class TheSportsDbAdapter:
    def __init__(
        self,
        *,
        sport: str,
        leagues: Iterable[str],
        api_key: str = DEFAULT_API_KEY,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self._sport = _normalize_sport(sport)
        self._league_names = _normalize_league_names(leagues)
        self._api_key = _normalize_api_key(api_key)
        self._user_agent = user_agent.strip() or DEFAULT_USER_AGENT
        self._catalog_lookup: dict[str, str] | None = None

    def get_scores(self, *, max_items: int = 6) -> list[SportsResult]:
        limit = max(1, int(max_items))
        if not self._league_names:
            return []

        now_utc = datetime.now(timezone.utc)
        combined: list[SportsResult] = []
        errors: list[str] = []

        for league_name in self._league_names:
            try:
                league_id = self._resolve_league_id(league_name)
                combined.extend(
                    self._load_league_scores(
                        league_id=league_id,
                        league_name=league_name,
                        now_utc=now_utc,
                    )
                )
            except SportsAdapterError as exc:
                errors.append(f"{league_name}: {exc}")

        deduped: dict[tuple[str, str, str, str], SportsResult] = {}
        for result in combined:
            key = (
                result.league.casefold(),
                result.home.casefold(),
                result.away.casefold(),
                result.start_time.isoformat(),
            )
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = result
                continue
            if existing.score == "--" and result.score != "--":
                deduped[key] = result

        ordered = sorted(deduped.values(), key=_result_sort_key)
        if not ordered and errors:
            raise SportsAdapterError("; ".join(errors))
        return ordered[:limit]

    def _load_league_scores(
        self,
        *,
        league_id: str,
        league_name: str,
        now_utc: datetime,
    ) -> list[SportsResult]:
        events: list[dict[str, Any]] = []
        endpoint_errors: list[str] = []
        for endpoint in (NEXT_EVENTS_ENDPOINT, PAST_EVENTS_ENDPOINT):
            url = _build_api_url(
                api_key=self._api_key,
                endpoint=endpoint,
                params={"id": league_id},
            )
            try:
                payload = _fetch_json(url, user_agent=self._user_agent)
            except SportsAdapterError as exc:
                endpoint_errors.append(str(exc))
                continue

            events_payload = payload.get("events")
            if isinstance(events_payload, list):
                for event in events_payload:
                    if isinstance(event, dict):
                        events.append(event)

        if not events and endpoint_errors:
            raise SportsAdapterError("; ".join(endpoint_errors))

        results: list[SportsResult] = []
        for event in events:
            parsed = self._parse_event(event, league_name=league_name, now_utc=now_utc)
            if parsed is not None:
                results.append(parsed)
        return results

    def _parse_event(
        self,
        payload: dict[str, Any],
        *,
        league_name: str,
        now_utc: datetime,
    ) -> SportsResult | None:
        home_team = _clean_text(payload.get("strHomeTeam"))
        away_team = _clean_text(payload.get("strAwayTeam"))
        if home_team is None or away_team is None:
            return None

        parsed_league_name = _clean_text(payload.get("strLeague")) or league_name
        start_time = _parse_event_start(payload, fallback=now_utc)
        score = _parse_score(payload)
        status = _derive_status(
            payload,
            start_time=start_time,
            has_score=score != "--",
            now_utc=now_utc,
        )

        return SportsResult(
            league=parsed_league_name,
            home=home_team,
            away=away_team,
            score=score,
            start_time=start_time,
            status=status,
        )

    def _resolve_league_id(self, league_name: str) -> str:
        raw = league_name.strip()
        if not raw:
            raise SportsAdapterError("sports league name must not be empty")

        if raw.isdigit():
            return raw

        if raw.lower().startswith("id:"):
            maybe_id = raw[3:].strip()
            if maybe_id.isdigit():
                return maybe_id

        normalized_key = _normalize_lookup_key(raw)
        alias_value = LEAGUE_ID_ALIASES.get(normalized_key)
        if alias_value is not None:
            return alias_value

        catalog_lookup = self._league_catalog_lookup()
        lookup_value = catalog_lookup.get(normalized_key)
        if lookup_value is not None:
            return lookup_value

        raise SportsAdapterError(
            f"Unable to resolve league '{raw}'. Use a known league name or an explicit id:<league_id>."
        )

    def _league_catalog_lookup(self) -> dict[str, str]:
        if self._catalog_lookup is not None:
            return self._catalog_lookup

        url = _build_api_url(api_key=self._api_key, endpoint="all_leagues.php")
        payload = _fetch_json(url, user_agent=self._user_agent)
        leagues_payload = payload.get("leagues")
        if not isinstance(leagues_payload, list):
            self._catalog_lookup = {}
            return self._catalog_lookup

        normalized_sport = self._sport.casefold()
        mapping: dict[str, str] = {}
        for item in leagues_payload:
            if not isinstance(item, dict):
                continue
            sport_name = _clean_text(item.get("strSport"))
            if sport_name is None or sport_name.casefold() != normalized_sport:
                continue
            league_id = _clean_text(item.get("idLeague"))
            league_name = _clean_text(item.get("strLeague"))
            if league_id is None or league_name is None:
                continue
            mapping[_normalize_lookup_key(league_name)] = league_id

        self._catalog_lookup = mapping
        return mapping

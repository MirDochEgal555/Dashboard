from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...domain.models import CalendarEvent
from .base import CalendarAdapterError

DEFAULT_TIMEOUT_SECONDS = 10


@dataclass(slots=True)
class _ParsedDateTime:
    value: datetime
    all_day: bool


def _read_ics_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            return path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            raise CalendarAdapterError(f"Unable to read ICS file: {path}") from exc
    except OSError as exc:
        raise CalendarAdapterError(f"Unable to read ICS file: {path}") from exc


def _fetch_ics_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "rpi-dashboard/0.1"})
    try:
        with urlopen(request, timeout=DEFAULT_TIMEOUT_SECONDS) as response:
            payload_bytes = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise CalendarAdapterError(f"Unable to fetch ICS URL: {url}") from exc

    for encoding in ("utf-8", "utf-8-sig"):
        try:
            return payload_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue

    raise CalendarAdapterError(f"Unable to decode ICS payload from URL: {url}")


def _unfold_lines(raw_text: str) -> list[str]:
    unfolded: list[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.rstrip("\r\n")
        if line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += line[1:]
            continue
        unfolded.append(line)
    return unfolded


def _parse_property(line: str) -> tuple[str, dict[str, str], str]:
    if ":" not in line:
        raise CalendarAdapterError("Malformed ICS property line")
    head, value = line.split(":", 1)

    tokens = head.split(";")
    name = tokens[0].strip().upper()
    params: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            continue
        key, raw_value = token.split("=", 1)
        params[key.strip().upper()] = raw_value.strip()

    return name, params, value.strip()


def _parse_compact_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise CalendarAdapterError(f"Invalid ICS date value: {value}") from exc


def _parse_compact_datetime(value: str) -> datetime:
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise CalendarAdapterError(f"Invalid ICS datetime value: {value}")


def _parse_date_or_datetime(
    *,
    value: str,
    params: dict[str, str],
    default_timezone: ZoneInfo,
) -> _ParsedDateTime:
    raw_value = value.strip()
    value_type = params.get("VALUE", "").upper()
    is_date = value_type == "DATE" or ("T" not in raw_value)
    if is_date:
        event_date = _parse_compact_date(raw_value)
        return _ParsedDateTime(
            value=datetime.combine(event_date, time.min, tzinfo=default_timezone),
            all_day=True,
        )

    tzid = params.get("TZID")
    if raw_value.endswith("Z"):
        parsed_utc = _parse_compact_datetime(raw_value[:-1]).replace(tzinfo=timezone.utc)
        return _ParsedDateTime(value=parsed_utc.astimezone(default_timezone), all_day=False)

    parsed = _parse_compact_datetime(raw_value)
    timezone_value: ZoneInfo = default_timezone
    if tzid:
        try:
            timezone_value = ZoneInfo(tzid)
        except ZoneInfoNotFoundError:
            timezone_value = default_timezone

    return _ParsedDateTime(
        value=parsed.replace(tzinfo=timezone_value).astimezone(default_timezone),
        all_day=False,
    )


def _parse_event_block(
    *,
    lines: list[str],
    source_name: str,
    default_timezone: ZoneInfo,
) -> CalendarEvent | None:
    summary: str | None = None
    dtstart: _ParsedDateTime | None = None
    dtend: _ParsedDateTime | None = None

    for raw_line in lines:
        if not raw_line.strip():
            continue
        name, params, value = _parse_property(raw_line)
        if name == "SUMMARY" and summary is None:
            summary = value.strip()
        elif name == "DTSTART" and dtstart is None:
            dtstart = _parse_date_or_datetime(
                value=value,
                params=params,
                default_timezone=default_timezone,
            )
        elif name == "DTEND" and dtend is None:
            dtend = _parse_date_or_datetime(
                value=value,
                params=params,
                default_timezone=default_timezone,
            )

    if dtstart is None:
        return None

    all_day = dtstart.all_day
    start_dt = dtstart.value
    if dtend is None:
        default_delta = timedelta(days=1) if all_day else timedelta(hours=1)
        end_dt = start_dt + default_delta
    else:
        all_day = all_day and dtend.all_day
        end_dt = dtend.value

    if end_dt <= start_dt:
        minimum_delta = timedelta(days=1) if all_day else timedelta(minutes=30)
        end_dt = start_dt + minimum_delta

    title = (summary or "").strip() or "Untitled event"
    return CalendarEvent(
        title=title,
        start_dt=start_dt,
        end_dt=end_dt,
        all_day=all_day,
        source=source_name,
    )


def _parse_events(
    *,
    lines: list[str],
    source_name: str,
    timezone_value: ZoneInfo,
) -> list[CalendarEvent]:
    events: list[CalendarEvent] = []
    event_lines: list[str] = []
    in_event = False

    for raw_line in lines:
        upper = raw_line.strip().upper()
        if upper == "BEGIN:VEVENT":
            in_event = True
            event_lines = []
            continue
        if upper == "END:VEVENT":
            if in_event:
                event = _parse_event_block(
                    lines=event_lines,
                    source_name=source_name,
                    default_timezone=timezone_value,
                )
                if event is not None:
                    events.append(event)
            in_event = False
            event_lines = []
            continue
        if in_event:
            event_lines.append(raw_line)

    return events


def _events_for_day_from_raw_text(
    *,
    raw_text: str,
    source_name: str,
    timezone_value: ZoneInfo,
    target_date: date,
) -> list[CalendarEvent]:
    unfolded_lines = _unfold_lines(raw_text)
    all_events = _parse_events(
        lines=unfolded_lines,
        source_name=source_name,
        timezone_value=timezone_value,
    )

    day_start = datetime.combine(target_date, time.min, tzinfo=timezone_value)
    day_end = day_start + timedelta(days=1)
    events_for_day = [
        event
        for event in all_events
        if event.start_dt < day_end and event.end_dt > day_start
    ]
    events_for_day.sort(key=lambda event: (event.start_dt, event.title.lower(), event.source.lower()))
    return events_for_day


class IcsCalendarAdapter:
    def __init__(
        self,
        *,
        path: Path,
        timezone_name: str,
        source_name: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._source_name = (source_name or "").strip() or self._path.stem or self._path.name
        try:
            self._timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise CalendarAdapterError(f"Unknown timezone for calendar adapter: {timezone_name}") from exc

    @property
    def source_name(self) -> str:
        return self._source_name

    def get_events_for_day(self, target_date: date) -> list[CalendarEvent]:
        raw_text = _read_ics_text(self._path)
        return _events_for_day_from_raw_text(
            raw_text=raw_text,
            source_name=self._source_name,
            timezone_value=self._timezone,
            target_date=target_date,
        )


class RemoteIcsCalendarAdapter:
    def __init__(
        self,
        *,
        url: str,
        timezone_name: str,
        source_name: str | None = None,
    ) -> None:
        self._url = url.strip()
        parsed = urlparse(self._url)
        default_source_name = parsed.netloc or "Remote ICS"
        self._source_name = (source_name or "").strip() or default_source_name
        try:
            self._timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise CalendarAdapterError(f"Unknown timezone for calendar adapter: {timezone_name}") from exc

    @property
    def source_name(self) -> str:
        return self._source_name

    def get_events_for_day(self, target_date: date) -> list[CalendarEvent]:
        raw_text = _fetch_ics_text(self._url)
        return _events_for_day_from_raw_text(
            raw_text=raw_text,
            source_name=self._source_name,
            timezone_value=self._timezone,
            target_date=target_date,
        )

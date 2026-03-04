from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .scheduler import (
    CALENDAR_REFRESH_CACHE_KEY,
    DUMMY_REFRESH_CACHE_KEY,
    FINANCE_REFRESH_CACHE_KEY,
    NEWS_REFRESH_CACHE_KEY,
    PHOTOS_REFRESH_CACHE_KEY,
    QUOTE_REFRESH_CACHE_KEY,
    SPORTS_REFRESH_CACHE_KEY,
    TRANSIT_REFRESH_CACHE_KEY,
    WEATHER_REFRESH_CACHE_KEY,
    build_scheduler,
    run_calendar_refresh_job,
    run_dummy_refresh_job,
    run_finance_refresh_job,
    run_news_refresh_job,
    run_photos_refresh_job,
    run_quote_refresh_job,
    run_sports_refresh_job,
    run_transit_refresh_job,
    run_weather_refresh_job,
)
from .settings import AppSettings, load_settings
from .storage.cache import get_cache_entry, get_cache_payload
from .storage.db import initialize_database

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

WIDGET_TITLES = {
    "calendar": "Calendar",
    "weather": "Weather",
    "transit": "Transit",
    "news": "News",
    "finance": "Finance",
    "sports": "Sports",
    "photo": "Photos",
    "quote": "Quote",
}

COMPONENT_TEMPLATES = {
    "calendar": "tile_calendar.html",
    "weather": "tile_weather.html",
    "transit": "tile_transit.html",
    "news": "tile_news.html",
    "finance": "tile_finance.html",
    "sports": "tile_sports.html",
    "photo": "tile_photo.html",
    "quote": "tile_quote.html",
}

WIDGET_CACHE_KEYS = {
    "calendar": CALENDAR_REFRESH_CACHE_KEY,
    "weather": WEATHER_REFRESH_CACHE_KEY,
    "transit": TRANSIT_REFRESH_CACHE_KEY,
    "news": NEWS_REFRESH_CACHE_KEY,
    "finance": FINANCE_REFRESH_CACHE_KEY,
    "sports": SPORTS_REFRESH_CACHE_KEY,
    "photo": PHOTOS_REFRESH_CACHE_KEY,
    "quote": QUOTE_REFRESH_CACHE_KEY,
}


def _updated_at(tzinfo=None) -> str:
    if tzinfo is None:
        return datetime.now().strftime("%H:%M")
    return datetime.now(tzinfo).strftime("%H:%M")


def _get_settings(request: Request) -> AppSettings:
    return request.app.state.settings


def _format_local_refresh(timestamp_utc: str | None, settings: AppSettings) -> str | None:
    if not timestamp_utc:
        return None
    try:
        parsed = datetime.fromisoformat(timestamp_utc)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local_dt = parsed.astimezone(settings.timezone)
    return local_dt.strftime("%H:%M:%S")


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    normalized_value = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_calendar_time_label(
    *,
    start_dt: datetime | None,
    end_dt: datetime | None,
    all_day: bool,
    timezone_value,
) -> str | None:
    if all_day:
        return "All day"
    if start_dt is None:
        return None

    local_start = start_dt.astimezone(timezone_value)
    if end_dt is None:
        return local_start.strftime("%H:%M")

    local_end = end_dt.astimezone(timezone_value)
    if local_end <= local_start:
        return local_start.strftime("%H:%M")

    if local_start.date() == local_end.date():
        return f"{local_start:%H:%M}-{local_end:%H:%M}"
    return f"{local_start:%H:%M}-{local_end:%a %H:%M}"


def _format_day_label(raw_date: Any) -> str:
    if not isinstance(raw_date, str):
        return "--"
    try:
        return datetime.fromisoformat(raw_date).strftime("%a")
    except ValueError:
        return raw_date


def _format_day_label_long(raw_date: Any) -> str:
    if not isinstance(raw_date, str):
        return "--"
    try:
        return datetime.fromisoformat(raw_date).strftime("%a, %b %d")
    except ValueError:
        return raw_date


def _format_headline_time_short(value: datetime | None, timezone_value) -> str | None:
    if value is None:
        return None
    local_value = value.astimezone(timezone_value)
    now_local = datetime.now(timezone_value)
    if local_value.date() == now_local.date():
        return local_value.strftime("%H:%M")
    return local_value.strftime("%a %H:%M")


def _format_headline_time_long(value: datetime | None, timezone_value) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone_value).strftime("%a, %b %d %H:%M")


def _format_price(value: float) -> str:
    return f"{value:,.2f}"


def _format_percent_change(value: float | None) -> str | None:
    if value is None:
        return None
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _change_direction(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def _sports_status_class(value: str | None) -> str:
    if value is None:
        return "scheduled"
    normalized = value.casefold()
    if any(token in normalized for token in ("live", "in play", "in progress", "half", "extra time", "pen")):
        return "live"
    if any(token in normalized for token in ("final", "finished", "full time", "ft")):
        return "final"
    if any(token in normalized for token in ("postponed", "cancelled", "canceled", "abandoned")):
        return "postponed"
    return "scheduled"


def _format_on_this_day_year_label(value: Any) -> str:
    year = _to_int(value)
    if year is None:
        return "--"
    return str(year)


def _finance_alias_lookup(settings: AppSettings) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for symbol, alias in settings.yaml.finance.aliases.items():
        normalized_symbol = symbol.strip().casefold()
        normalized_alias = alias.strip()
        if normalized_symbol and normalized_alias:
            aliases[normalized_symbol] = normalized_alias
    return aliases


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _format_clock_time(value: datetime | None, timezone_value) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone_value).strftime("%H:%M")


def _same_local_minute(left: datetime | None, right: datetime | None, timezone_value) -> bool:
    if left is None or right is None:
        return False
    left_value = left.astimezone(timezone_value).replace(second=0, microsecond=0)
    right_value = right.astimezone(timezone_value).replace(second=0, microsecond=0)
    return left_value == right_value


def _is_cancelled_status(status: str | None) -> bool:
    if status is None:
        return False
    normalized = status.casefold()
    return "cancelled" in normalized or "canceled" in normalized


def _normalize_photo_relative_path(raw_path: Any) -> str | None:
    if not isinstance(raw_path, str):
        return None
    normalized = raw_path.strip().replace("\\", "/")
    if not normalized:
        return None
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        return None
    return "/".join(parts)


def _build_photo_url(relative_path: str) -> str:
    return f"/photo-files/{quote(relative_path, safe='/')}"


def _build_weather_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "weather_available": False,
        "weather_temp_display": None,
        "weather_unit_symbol": "C",
        "weather_condition": None,
        "weather_location_label": None,
        "weather_daily": [],
        "weather_updated_at": None,
        "weather_is_stale": True,
    }

    cache_entry = get_cache_entry(settings.db_path, WEATHER_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return context

    units = payload.get("units")
    if units == "imperial":
        context["weather_unit_symbol"] = "F"

    context["weather_is_stale"] = cache_entry.is_stale()

    location_label = payload.get("location_label")
    if isinstance(location_label, str) and location_label.strip():
        context["weather_location_label"] = location_label.strip()

    refreshed_at = payload.get("refreshed_at_utc")
    snapshot_updated = snapshot.get("updated_at")
    context["weather_updated_at"] = (
        _format_local_refresh(refreshed_at, settings)
        or _format_local_refresh(snapshot_updated, settings)
    )

    temp = _to_float(snapshot.get("temp"))
    if temp is not None:
        context["weather_temp_display"] = f"{temp:.1f}"
        context["weather_available"] = True

    condition = snapshot.get("condition")
    if isinstance(condition, str) and condition.strip():
        context["weather_condition"] = condition.strip()

    daily_data = snapshot.get("daily")
    if isinstance(daily_data, list):
        daily_rows: list[dict[str, Any]] = []
        for item in daily_data[: settings.yaml.weather.show_daily_days]:
            if not isinstance(item, dict):
                continue
            min_temp = _to_float(item.get("min_temp"))
            max_temp = _to_float(item.get("max_temp"))
            if min_temp is None or max_temp is None:
                continue
            condition = item.get("condition")
            precip_prob = _to_int(item.get("precip_prob"))
            daily_rows.append(
                {
                    "day_label": _format_day_label(item.get("date")),
                    "max_temp_display": f"{max_temp:.0f}",
                    "min_temp_display": f"{min_temp:.0f}",
                    "condition": condition if isinstance(condition, str) else "",
                    "precip_prob": precip_prob,
                }
            )
        context["weather_daily"] = daily_rows

    return context


def _build_weather_modal_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "modal_weather_available": False,
        "modal_weather_temp_display": None,
        "modal_weather_unit_symbol": "C",
        "modal_weather_condition": None,
        "modal_weather_location_label": None,
        "modal_weather_provider_label": "Open-Meteo",
        "modal_weather_coordinates": None,
        "modal_weather_updated_at": None,
        "modal_weather_is_stale": True,
        "modal_weather_daily": [],
    }

    cache_entry = get_cache_entry(settings.db_path, WEATHER_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    snapshot = payload.get("snapshot")
    if not isinstance(snapshot, dict):
        return context

    provider = payload.get("provider")
    if isinstance(provider, str) and provider.strip():
        context["modal_weather_provider_label"] = provider.replace("_", " ").title()

    units = payload.get("units")
    if units == "imperial":
        context["modal_weather_unit_symbol"] = "F"

    context["modal_weather_is_stale"] = cache_entry.is_stale()

    location_label = payload.get("location_label")
    if isinstance(location_label, str) and location_label.strip():
        context["modal_weather_location_label"] = location_label.strip()

    lat = _to_float(payload.get("lat"))
    lon = _to_float(payload.get("lon"))
    if lat is not None and lon is not None:
        context["modal_weather_coordinates"] = f"{lat:.3f}, {lon:.3f}"

    refreshed_at = payload.get("refreshed_at_utc")
    snapshot_updated = snapshot.get("updated_at")
    context["modal_weather_updated_at"] = (
        _format_local_refresh(refreshed_at, settings)
        or _format_local_refresh(snapshot_updated, settings)
    )

    temp = _to_float(snapshot.get("temp"))
    if temp is not None:
        context["modal_weather_temp_display"] = f"{temp:.1f}"
        context["modal_weather_available"] = True

    condition = snapshot.get("condition")
    if isinstance(condition, str) and condition.strip():
        context["modal_weather_condition"] = condition.strip()

    daily_data = snapshot.get("daily")
    if isinstance(daily_data, list):
        daily_rows: list[dict[str, Any]] = []
        for item in daily_data[: settings.yaml.weather.show_daily_days]:
            if not isinstance(item, dict):
                continue
            min_temp = _to_float(item.get("min_temp"))
            max_temp = _to_float(item.get("max_temp"))
            if min_temp is None or max_temp is None:
                continue
            condition = item.get("condition")
            precip_prob = _to_int(item.get("precip_prob"))
            daily_rows.append(
                {
                    "day_label": _format_day_label_long(item.get("date")),
                    "condition": condition if isinstance(condition, str) and condition.strip() else "--",
                    "max_temp_display": f"{max_temp:.0f}",
                    "min_temp_display": f"{min_temp:.0f}",
                    "precip_display": f"{precip_prob}%" if precip_prob is not None else "--",
                }
            )
        context["modal_weather_daily"] = daily_rows

    return context


def _build_photo_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "photo_available": False,
        "photo_items": [],
        "photo_current_caption": None,
        "photo_total_count": 0,
        "photo_updated_at": None,
        "photo_is_stale": True,
        "photo_rotation_seconds": settings.yaml.ui.photo_rotation_seconds,
        "photos_folder_hint": settings.yaml.photos.folder.as_posix(),
    }

    cache_entry = get_cache_entry(settings.db_path, PHOTOS_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["photo_is_stale"] = cache_entry.is_stale()
    context["photo_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)

    items_data = payload.get("items")
    if not isinstance(items_data, list):
        return context

    items: list[dict[str, Any]] = []
    for item in items_data:
        if not isinstance(item, dict):
            continue
        path = _normalize_photo_relative_path(item.get("path"))
        if path is None:
            continue
        raw_caption = item.get("caption")
        caption = raw_caption.strip() if isinstance(raw_caption, str) and raw_caption.strip() else None
        items.append(
            {
                "url": _build_photo_url(path),
                "caption": caption,
            }
        )

    context["photo_items"] = items
    context["photo_total_count"] = len(items)
    if items:
        context["photo_available"] = True
        context["photo_current_caption"] = items[0]["caption"]

    return context


def _build_calendar_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "calendar_available": False,
        "calendar_events": [],
        "calendar_event_count": 0,
        "calendar_updated_at": None,
        "calendar_is_stale": True,
        "calendar_error_count": 0,
        "calendar_source_count": len(settings.yaml.calendar.sources),
        "calendar_show_time": settings.yaml.calendar.display.show_time,
        "calendar_show_title": settings.yaml.calendar.display.show_title,
    }

    cache_entry = get_cache_entry(settings.db_path, CALENDAR_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["calendar_is_stale"] = cache_entry.is_stale()
    context["calendar_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)

    source_count = _to_int(payload.get("source_count"))
    if source_count is not None and source_count >= 0:
        context["calendar_source_count"] = source_count

    error_count = _to_int(payload.get("error_count"))
    errors = payload.get("errors")
    if error_count is not None and error_count >= 0:
        context["calendar_error_count"] = error_count
    elif isinstance(errors, list):
        context["calendar_error_count"] = len(errors)

    events_data = payload.get("events")
    if not isinstance(events_data, list):
        return context

    event_rows: list[dict[str, Any]] = []
    for item in events_data[:8]:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue

        source = item.get("source")
        source_label = source.strip() if isinstance(source, str) and source.strip() else None
        start_dt = _parse_iso_datetime(item.get("start_dt"))
        end_dt = _parse_iso_datetime(item.get("end_dt"))
        all_day = bool(item.get("all_day"))
        time_label = _format_calendar_time_label(
            start_dt=start_dt,
            end_dt=end_dt,
            all_day=all_day,
            timezone_value=settings.timezone,
        )
        event_rows.append(
            {
                "title": title.strip(),
                "display_title": title.strip()
                if settings.yaml.calendar.display.show_title
                else "Busy",
                "source": source_label,
                "time_label": time_label,
            }
        )

    context["calendar_events"] = event_rows
    context["calendar_available"] = len(event_rows) > 0
    context["calendar_event_count"] = _to_int(payload.get("count")) or len(event_rows)
    return context


def _build_calendar_modal_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "modal_calendar_available": False,
        "modal_calendar_events": [],
        "modal_calendar_event_count": 0,
        "modal_calendar_updated_at": None,
        "modal_calendar_target_date": None,
        "modal_calendar_is_stale": True,
        "modal_calendar_source_count": len(settings.yaml.calendar.sources),
        "modal_calendar_error_messages": [],
    }

    cache_entry = get_cache_entry(settings.db_path, CALENDAR_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["modal_calendar_is_stale"] = cache_entry.is_stale()
    context["modal_calendar_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)

    target_date = payload.get("target_date")
    if isinstance(target_date, str) and target_date.strip():
        context["modal_calendar_target_date"] = target_date.strip()

    source_count = _to_int(payload.get("source_count"))
    if source_count is not None and source_count >= 0:
        context["modal_calendar_source_count"] = source_count

    errors = payload.get("errors")
    if isinstance(errors, list):
        error_messages = [
            item.strip() for item in errors if isinstance(item, str) and item.strip()
        ]
        context["modal_calendar_error_messages"] = error_messages

    events_data = payload.get("events")
    if not isinstance(events_data, list):
        return context

    event_rows: list[dict[str, Any]] = []
    for item in events_data:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        if not isinstance(title, str) or not title.strip():
            continue

        source = item.get("source")
        source_label = source.strip() if isinstance(source, str) and source.strip() else "--"
        start_dt = _parse_iso_datetime(item.get("start_dt"))
        end_dt = _parse_iso_datetime(item.get("end_dt"))
        all_day = bool(item.get("all_day"))

        time_label = _format_calendar_time_label(
            start_dt=start_dt,
            end_dt=end_dt,
            all_day=all_day,
            timezone_value=settings.timezone,
        ) or "--"

        if start_dt is not None:
            local_start = start_dt.astimezone(settings.timezone)
            start_display = local_start.strftime("%a, %b %d %H:%M")
        else:
            start_display = "--"

        if end_dt is not None:
            local_end = end_dt.astimezone(settings.timezone)
            end_display = local_end.strftime("%a, %b %d %H:%M")
        else:
            end_display = "--"

        event_rows.append(
            {
                "title": title.strip(),
                "display_title": title.strip()
                if settings.yaml.calendar.display.show_title
                else "Busy",
                "source": source_label,
                "time_label": time_label,
                "start_display": start_display,
                "end_display": end_display,
            }
        )

    context["modal_calendar_events"] = event_rows
    context["modal_calendar_available"] = len(event_rows) > 0
    context["modal_calendar_event_count"] = _to_int(payload.get("count")) or len(event_rows)
    return context


def _build_transit_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "transit_available": False,
        "transit_departures": [],
        "transit_departure_count": 0,
        "transit_stop_name": settings.yaml.transit.stop_name,
        "transit_horizon_minutes": settings.yaml.transit.horizon_minutes,
        "transit_updated_at": None,
        "transit_is_stale": True,
        "transit_has_error": False,
        "transit_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, TRANSIT_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["transit_is_stale"] = cache_entry.is_stale()
    context["transit_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    transit_error = _clean_text(payload.get("last_error"))
    context["transit_has_error"] = transit_error is not None
    context["transit_error_at"] = _format_local_refresh(payload.get("last_error_at_utc"), settings)

    stop_name = _clean_text(payload.get("stop_name"))
    if stop_name is not None:
        context["transit_stop_name"] = stop_name

    horizon_minutes = _to_int(payload.get("horizon_minutes"))
    if horizon_minutes is not None and horizon_minutes > 0:
        context["transit_horizon_minutes"] = horizon_minutes

    departures_data = payload.get("departures")
    if not isinstance(departures_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in departures_data[: settings.yaml.transit.max_departures]:
        if not isinstance(item, dict):
            continue

        planned_dt = _parse_iso_datetime(item.get("planned_time"))
        realtime_dt = _parse_iso_datetime(item.get("realtime_time"))
        active_dt = realtime_dt or planned_dt
        if active_dt is None:
            continue

        planned_display = _format_clock_time(planned_dt, settings.timezone)
        primary_display = _format_clock_time(active_dt, settings.timezone) or "--"
        secondary_display = None
        if (
            realtime_dt is not None
            and planned_dt is not None
            and not _same_local_minute(planned_dt, realtime_dt, settings.timezone)
        ):
            if planned_display is not None:
                secondary_display = f"sched {planned_display}"
        status_value = _clean_text(item.get("status"))

        rows.append(
            {
                "line": _clean_text(item.get("line")) or "?",
                "destination": _clean_text(item.get("destination")) or "Unknown destination",
                "status": status_value,
                "is_cancelled": _is_cancelled_status(status_value),
                "platform": _clean_text(item.get("platform")),
                "primary_time_display": primary_display,
                "secondary_time_display": secondary_display,
            }
        )

    context["transit_departures"] = rows
    context["transit_available"] = len(rows) > 0
    context["transit_departure_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_transit_modal_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "modal_transit_available": False,
        "modal_transit_departures": [],
        "modal_transit_departure_count": 0,
        "modal_transit_stop_name": settings.yaml.transit.stop_name,
        "modal_transit_stop_id": settings.yaml.transit.stop_id,
        "modal_transit_horizon_minutes": settings.yaml.transit.horizon_minutes,
        "modal_transit_provider_label": "Transport Rest",
        "modal_transit_updated_at": None,
        "modal_transit_is_stale": True,
        "modal_transit_has_error": False,
        "modal_transit_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, TRANSIT_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["modal_transit_is_stale"] = cache_entry.is_stale()
    context["modal_transit_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    transit_error = _clean_text(payload.get("last_error"))
    context["modal_transit_has_error"] = transit_error is not None
    context["modal_transit_error_at"] = _format_local_refresh(payload.get("last_error_at_utc"), settings)

    provider = _clean_text(payload.get("provider"))
    if provider is not None:
        context["modal_transit_provider_label"] = provider.replace("_", " ").title()

    stop_name = _clean_text(payload.get("stop_name"))
    if stop_name is not None:
        context["modal_transit_stop_name"] = stop_name

    stop_id = _clean_text(payload.get("stop_id"))
    if stop_id is not None:
        context["modal_transit_stop_id"] = stop_id

    horizon_minutes = _to_int(payload.get("horizon_minutes"))
    if horizon_minutes is not None and horizon_minutes > 0:
        context["modal_transit_horizon_minutes"] = horizon_minutes

    departures_data = payload.get("departures")
    if not isinstance(departures_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in departures_data:
        if not isinstance(item, dict):
            continue

        planned_dt = _parse_iso_datetime(item.get("planned_time"))
        realtime_dt = _parse_iso_datetime(item.get("realtime_time"))
        if planned_dt is None and realtime_dt is None:
            continue

        planned_display = _format_clock_time(planned_dt, settings.timezone) or "--"
        realtime_display = _format_clock_time(realtime_dt, settings.timezone)
        if realtime_dt is not None and planned_dt is not None and _same_local_minute(
            planned_dt,
            realtime_dt,
            settings.timezone,
        ):
            realtime_display = None
        status_value = _clean_text(item.get("status"))

        rows.append(
            {
                "line": _clean_text(item.get("line")) or "?",
                "destination": _clean_text(item.get("destination")) or "Unknown destination",
                "planned_display": planned_display,
                "realtime_display": realtime_display or "--",
                "platform": _clean_text(item.get("platform")) or "--",
                "status": status_value or "--",
                "is_cancelled": _is_cancelled_status(status_value),
            }
        )

    context["modal_transit_departures"] = rows
    context["modal_transit_available"] = len(rows) > 0
    context["modal_transit_departure_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_news_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "news_available": False,
        "news_headlines": [],
        "news_headline_count": 0,
        "news_feed_count": len(settings.yaml.news.feeds),
        "news_updated_at": None,
        "news_is_stale": True,
    }

    cache_entry = get_cache_entry(settings.db_path, NEWS_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["news_is_stale"] = cache_entry.is_stale()
    context["news_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)

    feed_count = _to_int(payload.get("feed_count"))
    if feed_count is not None and feed_count >= 0:
        context["news_feed_count"] = feed_count

    headlines_data = payload.get("headlines")
    if not isinstance(headlines_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in headlines_data[: settings.yaml.news.max_items]:
        if not isinstance(item, dict):
            continue

        title = _clean_text(item.get("title"))
        url = _clean_text(item.get("url"))
        if title is None or url is None:
            continue

        source = _clean_text(item.get("source")) or "Unknown source"
        published_dt = _parse_iso_datetime(item.get("published_at"))

        rows.append(
            {
                "title": title,
                "source": source,
                "url": url,
                "published_label": _format_headline_time_short(published_dt, settings.timezone),
            }
        )

    context["news_headlines"] = rows
    context["news_available"] = len(rows) > 0
    context["news_headline_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_news_modal_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "modal_news_available": False,
        "modal_news_headlines": [],
        "modal_news_headline_count": 0,
        "modal_news_feed_count": len(settings.yaml.news.feeds),
        "modal_news_provider_label": "RSS",
        "modal_news_updated_at": None,
        "modal_news_is_stale": True,
    }

    cache_entry = get_cache_entry(settings.db_path, NEWS_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["modal_news_is_stale"] = cache_entry.is_stale()
    context["modal_news_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)

    provider = _clean_text(payload.get("provider"))
    if provider is not None:
        context["modal_news_provider_label"] = provider.replace("_", " ").upper()

    feed_count = _to_int(payload.get("feed_count"))
    if feed_count is not None and feed_count >= 0:
        context["modal_news_feed_count"] = feed_count

    headlines_data = payload.get("headlines")
    if not isinstance(headlines_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in headlines_data:
        if not isinstance(item, dict):
            continue

        title = _clean_text(item.get("title"))
        url = _clean_text(item.get("url"))
        if title is None or url is None:
            continue

        source = _clean_text(item.get("source")) or "Unknown source"
        published_dt = _parse_iso_datetime(item.get("published_at"))

        rows.append(
            {
                "title": title,
                "source": source,
                "url": url,
                "published_label": _format_headline_time_long(published_dt, settings.timezone),
            }
        )

    context["modal_news_headlines"] = rows
    context["modal_news_available"] = len(rows) > 0
    context["modal_news_headline_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_finance_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "finance_available": False,
        "finance_quotes": [],
        "finance_quote_count": 0,
        "finance_stocks_count": len(settings.yaml.finance.symbols.stocks),
        "finance_crypto_count": len(settings.yaml.finance.symbols.crypto),
        "finance_updated_at": None,
        "finance_is_stale": True,
        "finance_has_error": False,
        "finance_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, FINANCE_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    alias_lookup = _finance_alias_lookup(settings)
    payload_stocks = payload.get("stocks")
    if isinstance(payload_stocks, list):
        stock_symbols = {
            item.strip().casefold()
            for item in payload_stocks
            if isinstance(item, str) and item.strip()
        }
    else:
        stock_symbols = {symbol.casefold() for symbol in settings.yaml.finance.symbols.stocks}
    context["finance_is_stale"] = cache_entry.is_stale()
    context["finance_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    finance_error = _clean_text(payload.get("last_error"))
    context["finance_has_error"] = finance_error is not None
    context["finance_error_at"] = _format_local_refresh(payload.get("last_error_at_utc"), settings)

    quotes_data = payload.get("quotes")
    if not isinstance(quotes_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in quotes_data[: settings.yaml.finance.max_items]:
        if not isinstance(item, dict):
            continue

        symbol = _clean_text(item.get("symbol"))
        price = _to_float(item.get("price"))
        change = _to_float(item.get("change"))
        updated_at = _parse_iso_datetime(item.get("updated_at"))

        if symbol is None or price is None:
            continue

        is_stock = symbol.casefold() in stock_symbols
        display_name = alias_lookup.get(symbol.casefold(), symbol)
        rows.append(
            {
                "display_name": display_name,
                "symbol": symbol,
                "price_display": _format_price(price),
                "change_display": _format_percent_change(change),
                "change_direction": _change_direction(change),
                "updated_label": _format_clock_time(updated_at, settings.timezone),
                "show_symbol": display_name != symbol,
                "change_label": "24h" if is_stock else None,
            }
        )

    context["finance_quotes"] = rows
    context["finance_available"] = len(rows) > 0
    context["finance_quote_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_finance_modal_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "modal_finance_available": False,
        "modal_finance_quotes": [],
        "modal_finance_quote_count": 0,
        "modal_finance_stocks_count": len(settings.yaml.finance.symbols.stocks),
        "modal_finance_crypto_count": len(settings.yaml.finance.symbols.crypto),
        "modal_finance_provider_label": "Stooq + CoinGecko",
        "modal_finance_updated_at": None,
        "modal_finance_is_stale": True,
        "modal_finance_has_error": False,
        "modal_finance_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, FINANCE_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    alias_lookup = _finance_alias_lookup(settings)
    payload_stocks = payload.get("stocks")
    if isinstance(payload_stocks, list):
        stock_symbols = {
            item.strip().casefold()
            for item in payload_stocks
            if isinstance(item, str) and item.strip()
        }
    else:
        stock_symbols = {symbol.casefold() for symbol in settings.yaml.finance.symbols.stocks}
    context["modal_finance_is_stale"] = cache_entry.is_stale()
    context["modal_finance_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    finance_error = _clean_text(payload.get("last_error"))
    context["modal_finance_has_error"] = finance_error is not None
    context["modal_finance_error_at"] = _format_local_refresh(payload.get("last_error_at_utc"), settings)

    provider = _clean_text(payload.get("provider"))
    if provider is not None:
        context["modal_finance_provider_label"] = provider.replace("_", " ").title()

    stocks_data = payload.get("stocks")
    if isinstance(stocks_data, list):
        context["modal_finance_stocks_count"] = len(stocks_data)
    crypto_data = payload.get("crypto")
    if isinstance(crypto_data, list):
        context["modal_finance_crypto_count"] = len(crypto_data)

    quotes_data = payload.get("quotes")
    if not isinstance(quotes_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in quotes_data:
        if not isinstance(item, dict):
            continue

        symbol = _clean_text(item.get("symbol"))
        price = _to_float(item.get("price"))
        change = _to_float(item.get("change"))
        updated_at = _parse_iso_datetime(item.get("updated_at"))

        if symbol is None or price is None:
            continue

        is_stock = symbol.casefold() in stock_symbols
        display_name = alias_lookup.get(symbol.casefold(), symbol)
        rows.append(
            {
                "display_name": display_name,
                "symbol": symbol,
                "price_display": _format_price(price),
                "change_display": _format_percent_change(change) or "--",
                "change_direction": _change_direction(change),
                "updated_label": _format_headline_time_long(updated_at, settings.timezone) or "--",
                "show_symbol": display_name != symbol,
                "change_label": "24h" if is_stock else None,
            }
        )

    context["modal_finance_quotes"] = rows
    context["modal_finance_available"] = len(rows) > 0
    context["modal_finance_quote_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_sports_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "sports_available": False,
        "sports_scores": [],
        "sports_score_count": 0,
        "sports_league_count": len(settings.yaml.sports.leagues),
        "sports_updated_at": None,
        "sports_is_stale": True,
        "sports_has_error": False,
        "sports_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, SPORTS_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["sports_is_stale"] = cache_entry.is_stale()
    context["sports_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    sports_error = _clean_text(payload.get("last_error"))
    context["sports_has_error"] = sports_error is not None
    context["sports_error_at"] = _format_local_refresh(payload.get("last_error_at_utc"), settings)

    leagues_data = payload.get("leagues")
    if isinstance(leagues_data, list):
        context["sports_league_count"] = len(
            [item for item in leagues_data if isinstance(item, str) and item.strip()]
        )

    scores_data = payload.get("scores")
    if not isinstance(scores_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in scores_data[: settings.yaml.sports.max_items]:
        if not isinstance(item, dict):
            continue

        league = _clean_text(item.get("league")) or "League"
        home = _clean_text(item.get("home"))
        away = _clean_text(item.get("away"))
        if home is None or away is None:
            continue

        status = _clean_text(item.get("status")) or "Scheduled"
        start_time = _parse_iso_datetime(item.get("start_time"))
        rows.append(
            {
                "league": league,
                "home": home,
                "away": away,
                "score_display": _clean_text(item.get("score")) or "--",
                "status": status,
                "status_class": _sports_status_class(status),
                "start_label": _format_headline_time_short(start_time, settings.timezone) or "--",
            }
        )

    context["sports_scores"] = rows
    context["sports_available"] = len(rows) > 0
    context["sports_score_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_sports_modal_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "modal_sports_available": False,
        "modal_sports_scores": [],
        "modal_sports_score_count": 0,
        "modal_sports_league_count": len(settings.yaml.sports.leagues),
        "modal_sports_provider_label": "TheSportsDB",
        "modal_sports_updated_at": None,
        "modal_sports_is_stale": True,
        "modal_sports_has_error": False,
        "modal_sports_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, SPORTS_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["modal_sports_is_stale"] = cache_entry.is_stale()
    context["modal_sports_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    sports_error = _clean_text(payload.get("last_error"))
    context["modal_sports_has_error"] = sports_error is not None
    context["modal_sports_error_at"] = _format_local_refresh(
        payload.get("last_error_at_utc"), settings
    )

    provider = _clean_text(payload.get("provider"))
    if provider is not None:
        context["modal_sports_provider_label"] = provider.replace("_", " ").title()

    leagues_data = payload.get("leagues")
    if isinstance(leagues_data, list):
        context["modal_sports_league_count"] = len(
            [item for item in leagues_data if isinstance(item, str) and item.strip()]
        )

    scores_data = payload.get("scores")
    if not isinstance(scores_data, list):
        return context

    rows: list[dict[str, Any]] = []
    for item in scores_data:
        if not isinstance(item, dict):
            continue

        league = _clean_text(item.get("league")) or "League"
        home = _clean_text(item.get("home"))
        away = _clean_text(item.get("away"))
        if home is None or away is None:
            continue

        status = _clean_text(item.get("status")) or "Scheduled"
        start_time = _parse_iso_datetime(item.get("start_time"))
        rows.append(
            {
                "league": league,
                "home": home,
                "away": away,
                "score_display": _clean_text(item.get("score")) or "--",
                "status": status,
                "status_class": _sports_status_class(status),
                "start_label": _format_headline_time_long(start_time, settings.timezone) or "--",
            }
        )

    context["modal_sports_scores"] = rows
    context["modal_sports_available"] = len(rows) > 0
    context["modal_sports_score_count"] = _to_int(payload.get("count")) or len(rows)
    return context


def _build_quote_tile_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "quote_available": False,
        "quote_text": None,
        "quote_author": None,
        "quote_source": None,
        "quote_updated_at": None,
        "quote_is_stale": True,
        "quote_on_this_day": [],
        "quote_on_this_day_count": 0,
        "quote_has_error": False,
        "quote_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, QUOTE_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["quote_is_stale"] = cache_entry.is_stale()
    context["quote_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    quote_error = _clean_text(payload.get("last_error"))
    context["quote_has_error"] = quote_error is not None
    context["quote_error_at"] = _format_local_refresh(payload.get("last_error_at_utc"), settings)

    quote_data = payload.get("quote")
    if isinstance(quote_data, dict):
        quote_text = _clean_text(quote_data.get("text"))
        quote_author = _clean_text(quote_data.get("author"))
        quote_source = _clean_text(quote_data.get("source"))
        if quote_text is not None:
            context["quote_text"] = quote_text
            context["quote_author"] = quote_author or "Unknown"
            context["quote_source"] = quote_source or "Quote"
            context["quote_available"] = True

    on_this_day_data = payload.get("on_this_day")
    if isinstance(on_this_day_data, list):
        rows: list[dict[str, Any]] = []
        for item in on_this_day_data[: settings.yaml.quotes.max_on_this_day_items]:
            if not isinstance(item, dict):
                continue
            text = _clean_text(item.get("text"))
            if text is None:
                continue
            rows.append(
                {
                    "year_label": _format_on_this_day_year_label(item.get("year")),
                    "text": text,
                    "source": _clean_text(item.get("source")),
                }
            )
        context["quote_on_this_day"] = rows
        context["quote_on_this_day_count"] = _to_int(payload.get("on_this_day_count")) or len(rows)
        if rows:
            context["quote_available"] = True

    return context


def _build_quote_modal_context(settings: AppSettings) -> dict[str, Any]:
    context: dict[str, Any] = {
        "modal_quote_available": False,
        "modal_quote_text": None,
        "modal_quote_author": None,
        "modal_quote_source": None,
        "modal_quote_updated_at": None,
        "modal_quote_is_stale": True,
        "modal_quote_on_this_day": [],
        "modal_quote_on_this_day_count": 0,
        "modal_quote_on_this_day_provider_label": "Wikipedia",
        "modal_quote_has_error": False,
        "modal_quote_error_at": None,
    }

    cache_entry = get_cache_entry(settings.db_path, QUOTE_REFRESH_CACHE_KEY)
    if cache_entry is None or not isinstance(cache_entry.payload, dict):
        return context

    payload = cache_entry.payload
    context["modal_quote_is_stale"] = cache_entry.is_stale()
    context["modal_quote_updated_at"] = _format_local_refresh(payload.get("refreshed_at_utc"), settings)
    quote_error = _clean_text(payload.get("last_error"))
    context["modal_quote_has_error"] = quote_error is not None
    context["modal_quote_error_at"] = _format_local_refresh(payload.get("last_error_at_utc"), settings)

    on_this_day_provider = _clean_text(payload.get("on_this_day_provider"))
    if on_this_day_provider is not None:
        context["modal_quote_on_this_day_provider_label"] = on_this_day_provider.replace("_", " ").title()

    quote_data = payload.get("quote")
    if isinstance(quote_data, dict):
        quote_text = _clean_text(quote_data.get("text"))
        quote_author = _clean_text(quote_data.get("author"))
        quote_source = _clean_text(quote_data.get("source"))
        if quote_text is not None:
            context["modal_quote_text"] = quote_text
            context["modal_quote_author"] = quote_author or "Unknown"
            context["modal_quote_source"] = quote_source or "Quote"
            context["modal_quote_available"] = True

    on_this_day_data = payload.get("on_this_day")
    if isinstance(on_this_day_data, list):
        rows: list[dict[str, Any]] = []
        for item in on_this_day_data:
            if not isinstance(item, dict):
                continue
            text = _clean_text(item.get("text"))
            if text is None:
                continue
            rows.append(
                {
                    "year_label": _format_on_this_day_year_label(item.get("year")),
                    "text": text,
                    "source": _clean_text(item.get("source")),
                    "url": _clean_text(item.get("url")),
                }
            )
        context["modal_quote_on_this_day"] = rows
        context["modal_quote_on_this_day_count"] = _to_int(payload.get("on_this_day_count")) or len(rows)

    return context


def _component_response(request: Request, widget_name: str) -> HTMLResponse:
    settings = _get_settings(request)
    template_name = COMPONENT_TEMPLATES[widget_name]
    return templates.TemplateResponse(
        f"components/{template_name}",
        {"request": request, "updated_at": _updated_at(settings.timezone)},
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = load_settings()
    initialize_database(settings.db_path)
    run_dummy_refresh_job(settings)
    run_calendar_refresh_job(settings)
    run_weather_refresh_job(settings)
    run_transit_refresh_job(settings)
    run_photos_refresh_job(settings)
    run_news_refresh_job(settings)
    run_finance_refresh_job(settings)
    run_sports_refresh_job(settings)
    run_quote_refresh_job(settings)
    scheduler = build_scheduler(settings)
    scheduler.start()

    application.state.settings = settings
    application.state.scheduler = scheduler
    application.state.started_at_utc = datetime.now(timezone.utc)

    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Raspberry Pi Dashboard", version="0.1.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    now_local = datetime.now(settings.timezone)

    dummy_refresh = get_cache_payload(
        settings.db_path,
        DUMMY_REFRESH_CACHE_KEY,
        allow_stale=True,
    )
    refresh_display = None
    if isinstance(dummy_refresh, dict):
        refresh_display = _format_local_refresh(dummy_refresh.get("refreshed_at_utc"), settings)

    calendar_context = _build_calendar_tile_context(settings)
    weather_context = _build_weather_tile_context(settings)
    transit_context = _build_transit_tile_context(settings)
    news_context = _build_news_tile_context(settings)
    finance_context = _build_finance_tile_context(settings)
    sports_context = _build_sports_tile_context(settings)
    photo_context = _build_photo_tile_context(settings)
    quote_context = _build_quote_tile_context(settings)

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "now_local": now_local,
            "generated_at": _updated_at(settings.timezone),
            "title": settings.yaml.ui.title,
            "left_column_width": settings.yaml.ui.layout.left_column_width,
            "right_rotation_seconds": settings.yaml.ui.layout.right_rotation_seconds,
            "refresh_interval_minutes": settings.yaml.refresh.interval_minutes,
            "environment": settings.env.dashboard_env,
            "timezone_name": settings.env.dashboard_timezone,
            "dummy_refresh_display": refresh_display,
            "scheduler_running": request.app.state.scheduler.running,
            **calendar_context,
            **weather_context,
            **transit_context,
            **news_context,
            **finance_context,
            **sports_context,
            **photo_context,
            **quote_context,
        },
    )


@app.get("/health", response_class=JSONResponse)
async def health(request: Request) -> JSONResponse:
    settings = _get_settings(request)
    dummy_entry = get_cache_entry(settings.db_path, DUMMY_REFRESH_CACHE_KEY)
    calendar_entry = get_cache_entry(settings.db_path, CALENDAR_REFRESH_CACHE_KEY)
    weather_entry = get_cache_entry(settings.db_path, WEATHER_REFRESH_CACHE_KEY)
    transit_entry = get_cache_entry(settings.db_path, TRANSIT_REFRESH_CACHE_KEY)
    news_entry = get_cache_entry(settings.db_path, NEWS_REFRESH_CACHE_KEY)
    finance_entry = get_cache_entry(settings.db_path, FINANCE_REFRESH_CACHE_KEY)
    sports_entry = get_cache_entry(settings.db_path, SPORTS_REFRESH_CACHE_KEY)
    photos_entry = get_cache_entry(settings.db_path, PHOTOS_REFRESH_CACHE_KEY)
    quote_entry = get_cache_entry(settings.db_path, QUOTE_REFRESH_CACHE_KEY)

    return JSONResponse(
        {
            "status": "ok",
            "service": "rpi-dashboard",
            "environment": settings.env.dashboard_env,
            "timezone": settings.env.dashboard_timezone,
            "scheduler_running": request.app.state.scheduler.running,
            "dummy_refresh": dummy_entry.payload if dummy_entry else None,
            "calendar_refresh": calendar_entry.payload if calendar_entry else None,
            "weather_refresh": weather_entry.payload if weather_entry else None,
            "transit_refresh": transit_entry.payload if transit_entry else None,
            "news_refresh": news_entry.payload if news_entry else None,
            "finance_refresh": finance_entry.payload if finance_entry else None,
            "sports_refresh": sports_entry.payload if sports_entry else None,
            "photos_refresh": photos_entry.payload if photos_entry else None,
            "quote_refresh": quote_entry.payload if quote_entry else None,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/partials/calendar", response_class=HTMLResponse)
async def partial_calendar(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    calendar_context = _build_calendar_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_calendar.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **calendar_context,
        },
    )


@app.get("/partials/weather", response_class=HTMLResponse)
async def partial_weather(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    weather_context = _build_weather_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_weather.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **weather_context,
        },
    )


@app.get("/partials/transit", response_class=HTMLResponse)
async def partial_transit(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    transit_context = _build_transit_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_transit.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **transit_context,
        },
    )


@app.get("/partials/news", response_class=HTMLResponse)
async def partial_news(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    news_context = _build_news_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_news.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **news_context,
        },
    )


@app.get("/partials/finance", response_class=HTMLResponse)
async def partial_finance(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    finance_context = _build_finance_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_finance.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **finance_context,
        },
    )


@app.get("/partials/sports", response_class=HTMLResponse)
async def partial_sports(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    sports_context = _build_sports_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_sports.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **sports_context,
        },
    )


@app.get("/partials/photo", response_class=HTMLResponse)
async def partial_photo(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    photo_context = _build_photo_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_photo.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **photo_context,
        },
    )


@app.get("/partials/quote", response_class=HTMLResponse)
async def partial_quote(request: Request) -> HTMLResponse:
    settings = _get_settings(request)
    quote_context = _build_quote_tile_context(settings)
    return templates.TemplateResponse(
        "components/tile_quote.html",
        {
            "request": request,
            "updated_at": _updated_at(settings.timezone),
            **quote_context,
        },
    )


@app.get("/photo-files/{photo_path:path}", response_class=FileResponse)
async def photo_file(request: Request, photo_path: str) -> FileResponse:
    settings = _get_settings(request)
    normalized_path = _normalize_photo_relative_path(photo_path)
    if normalized_path is None:
        raise HTTPException(status_code=404, detail="Photo not found")

    root_path = settings.photos_path.resolve()
    target_path = (root_path / normalized_path).resolve()
    try:
        target_path.relative_to(root_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Photo not found") from exc

    if target_path.suffix.lower() not in settings.yaml.photos.extensions:
        raise HTTPException(status_code=404, detail="Photo not found")
    if not target_path.is_file():
        raise HTTPException(status_code=404, detail="Photo not found")

    return FileResponse(target_path)


@app.get("/modals/{widget_name}", response_class=HTMLResponse)
async def modal(request: Request, widget_name: str) -> HTMLResponse:
    settings = _get_settings(request)
    widget_title = WIDGET_TITLES.get(widget_name)
    if widget_title is None:
        raise HTTPException(status_code=404, detail="Unknown widget")

    cached_payload: Any | None = None
    cache_key = WIDGET_CACHE_KEYS.get(widget_name)
    if cache_key is not None:
        cached_payload = get_cache_payload(settings.db_path, cache_key, allow_stale=True)

    payload_preview = None
    if cached_payload is not None:
        payload_preview = json.dumps(cached_payload, indent=2, ensure_ascii=False)

    weather_modal_context: dict[str, Any] = {}
    if widget_name == "weather":
        weather_modal_context = _build_weather_modal_context(settings)

    calendar_modal_context: dict[str, Any] = {}
    if widget_name == "calendar":
        calendar_modal_context = _build_calendar_modal_context(settings)

    transit_modal_context: dict[str, Any] = {}
    if widget_name == "transit":
        transit_modal_context = _build_transit_modal_context(settings)

    news_modal_context: dict[str, Any] = {}
    if widget_name == "news":
        news_modal_context = _build_news_modal_context(settings)

    finance_modal_context: dict[str, Any] = {}
    if widget_name == "finance":
        finance_modal_context = _build_finance_modal_context(settings)

    sports_modal_context: dict[str, Any] = {}
    if widget_name == "sports":
        sports_modal_context = _build_sports_modal_context(settings)

    quote_modal_context: dict[str, Any] = {}
    if widget_name == "quote":
        quote_modal_context = _build_quote_modal_context(settings)

    return templates.TemplateResponse(
        "components/modal.html",
        {
            "request": request,
            "widget_name": widget_name,
            "widget_title": widget_title,
            "is_weather_widget": widget_name == "weather",
            "is_calendar_widget": widget_name == "calendar",
            "is_transit_widget": widget_name == "transit",
            "is_news_widget": widget_name == "news",
            "is_finance_widget": widget_name == "finance",
            "is_sports_widget": widget_name == "sports",
            "is_quote_widget": widget_name == "quote",
            "updated_at": _updated_at(settings.timezone),
            "cache_key": cache_key,
            "cached_payload_preview": payload_preview,
            **weather_modal_context,
            **calendar_modal_context,
            **transit_modal_context,
            **news_modal_context,
            **finance_modal_context,
            **sports_modal_context,
            **quote_modal_context,
        },
    )

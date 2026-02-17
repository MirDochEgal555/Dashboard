from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .scheduler import (
    DUMMY_REFRESH_CACHE_KEY,
    WEATHER_REFRESH_CACHE_KEY,
    build_scheduler,
    run_dummy_refresh_job,
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
    "photo": "Photo",
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
    "calendar": "calendar.today",
    "weather": WEATHER_REFRESH_CACHE_KEY,
    "transit": "transit.departures",
    "news": "news.headlines",
    "finance": "finance.quotes",
    "sports": "sports.scores",
    "photo": "photos.index",
    "quote": "quote.current",
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
    run_weather_refresh_job(settings)
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

    weather_context = _build_weather_tile_context(settings)

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
            **weather_context,
        },
    )


@app.get("/health", response_class=JSONResponse)
async def health(request: Request) -> JSONResponse:
    settings = _get_settings(request)
    dummy_entry = get_cache_entry(settings.db_path, DUMMY_REFRESH_CACHE_KEY)
    weather_entry = get_cache_entry(settings.db_path, WEATHER_REFRESH_CACHE_KEY)

    return JSONResponse(
        {
            "status": "ok",
            "service": "rpi-dashboard",
            "environment": settings.env.dashboard_env,
            "timezone": settings.env.dashboard_timezone,
            "scheduler_running": request.app.state.scheduler.running,
            "dummy_refresh": dummy_entry.payload if dummy_entry else None,
            "weather_refresh": weather_entry.payload if weather_entry else None,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/partials/calendar", response_class=HTMLResponse)
async def partial_calendar(request: Request) -> HTMLResponse:
    return _component_response(request, "calendar")


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
    return _component_response(request, "transit")


@app.get("/partials/news", response_class=HTMLResponse)
async def partial_news(request: Request) -> HTMLResponse:
    return _component_response(request, "news")


@app.get("/partials/finance", response_class=HTMLResponse)
async def partial_finance(request: Request) -> HTMLResponse:
    return _component_response(request, "finance")


@app.get("/partials/sports", response_class=HTMLResponse)
async def partial_sports(request: Request) -> HTMLResponse:
    return _component_response(request, "sports")


@app.get("/partials/photo", response_class=HTMLResponse)
async def partial_photo(request: Request) -> HTMLResponse:
    return _component_response(request, "photo")


@app.get("/partials/quote", response_class=HTMLResponse)
async def partial_quote(request: Request) -> HTMLResponse:
    return _component_response(request, "quote")


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

    return templates.TemplateResponse(
        "components/modal.html",
        {
            "request": request,
            "widget_name": widget_name,
            "widget_title": widget_title,
            "is_weather_widget": widget_name == "weather",
            "updated_at": _updated_at(settings.timezone),
            "cache_key": cache_key,
            "cached_payload_preview": payload_preview,
            **weather_modal_context,
        },
    )

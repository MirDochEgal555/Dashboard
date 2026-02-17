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

from .scheduler import DUMMY_REFRESH_CACHE_KEY, build_scheduler, run_dummy_refresh_job
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
    "weather": "weather.snapshot",
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
        },
    )


@app.get("/health", response_class=JSONResponse)
async def health(request: Request) -> JSONResponse:
    settings = _get_settings(request)
    dummy_entry = get_cache_entry(settings.db_path, DUMMY_REFRESH_CACHE_KEY)

    return JSONResponse(
        {
            "status": "ok",
            "service": "rpi-dashboard",
            "environment": settings.env.dashboard_env,
            "timezone": settings.env.dashboard_timezone,
            "scheduler_running": request.app.state.scheduler.running,
            "dummy_refresh": dummy_entry.payload if dummy_entry else None,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.get("/partials/calendar", response_class=HTMLResponse)
async def partial_calendar(request: Request) -> HTMLResponse:
    return _component_response(request, "calendar")


@app.get("/partials/weather", response_class=HTMLResponse)
async def partial_weather(request: Request) -> HTMLResponse:
    return _component_response(request, "weather")


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

    return templates.TemplateResponse(
        "components/modal.html",
        {
            "request": request,
            "widget_name": widget_name,
            "widget_title": widget_title,
            "updated_at": _updated_at(settings.timezone),
            "cache_key": cache_key,
            "cached_payload_preview": payload_preview,
        },
    )

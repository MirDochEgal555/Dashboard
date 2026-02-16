from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

app = FastAPI(title="Raspberry Pi Dashboard", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
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


def _updated_at() -> str:
    return datetime.now().strftime("%H:%M")


def _component_response(request: Request, widget_name: str) -> HTMLResponse:
    template_name = COMPONENT_TEMPLATES[widget_name]
    return templates.TemplateResponse(
        f"components/{template_name}",
        {"request": request, "updated_at": _updated_at()},
    )


@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "now_local": datetime.now(),
            "generated_at": _updated_at(),
            "title": "Raspberry Pi Dashboard",
            "right_rotation_seconds": 60,
        },
    )


@app.get("/health", response_class=JSONResponse)
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "service": "rpi-dashboard",
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
    widget_title = WIDGET_TITLES.get(widget_name)
    if widget_title is None:
        raise HTTPException(status_code=404, detail="Unknown widget")
    return templates.TemplateResponse(
        "components/modal.html",
        {
            "request": request,
            "widget_name": widget_name,
            "widget_title": widget_title,
            "updated_at": _updated_at(),
        },
    )


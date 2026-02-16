# Raspberry Pi Dashboard (Local-First Web/Kiosk) — Project Specification

This document is the **single source of truth** for setting up and building a Python dashboard project that runs locally on your Windows machine now and later runs on a Raspberry Pi connected to a monitor.

---

## 0) Your chosen preferences (captured)

- **Dev OS now:** Windows
- **Raspberry Pi model:** unknown (must work across Pi 3/4/5)
- **Display mode on Pi:** mixed / not sure (support kiosk fullscreen + optional windowed)
- **Inputs:** none (display-only)
- **UI tech:** web dashboard (local server + browser)
- **Visual style:** dense “control room” (lots of tiles)
- **Layout:** left column fixed + rotating right-side content
- **Resolution:** unknown (must auto-scale responsively)
- **Refresh cadence:** every 5–15 minutes
- **Offline behavior:** doesn’t matter (but implement graceful degradation)
- **Logging:** basic console logs
- **Calendars:** multiple sources
- **Auth/secrets:** API key / token via env vars
- **Calendar range:** today only
- **Calendar fields:** title + time
- **Weather location:** auto (device location, with fallback)
- **Weather provider:** free (recommended)
- **Weather display:** current + daily forecast
- **Transport region:** Germany
- **Transport content:** next departures from a stop/station
- **Transport source:** official API / GTFS-RT where possible
- **Photos:** local folder, rotating every N minutes
- **Extras:** news headlines + stocks/crypto + sports scores + quotes/on-this-day
- **Interactivity:** yes (click/tap to expand)
- **Sensitive info:** yes (calendar titles shown)
- **Packaging:** recommend best
- **Config:** mixed (env for secrets + yaml/toml for layout)

---

## 1) Goal

Build a **local web dashboard** that shows important current information on one screen and can be run:

1) **Locally** on your Windows machine during development  
2) **On a Raspberry Pi** later, displaying full-screen in a browser (“kiosk mode”) on an attached monitor  

The dashboard is meant to be always-on (or easy to start), auto-refreshing, visually dense, and resilient to partial data failures.

---

## 2) UX specification

### 2.1 Screen structure

Two major regions:

- **Left column (fixed)**
  - Current date/time
  - Today’s calendar events (multi-source)
  - Weather summary (current + daily)
  - Status line (e.g., last refresh time)

- **Right region (rotating panels)**
  - Public transport departures (Germany)
  - News headlines
  - Stocks/crypto snapshot
  - Sports scores
  - Local photo slideshow
  - Quote / “On this day”

Rotation cadence is independent from data refresh cadence.

### 2.2 Interactivity

- Clicking/tapping a tile opens an **expanded view** (modal overlay).
- The app should work without keyboard/mouse.

### 2.3 Responsiveness

- Must auto-scale for unknown monitor resolution.
- Use responsive CSS grid, `clamp()` for font sizes, and avoid fixed pixel heights.

---

## 3) Architecture overview

### 3.1 Recommended tech stack (Pi-friendly)

- **Python 3.11** target (3.10 acceptable if needed on Pi)
- **FastAPI** for the local web server
- **Uvicorn** as ASGI server
- **Jinja2** templates for server-rendered HTML
- **HTMX** for partial refresh + interactions (lightweight; no SPA required)
- **SQLite** for caching fetched data (simple, reliable)
- **Pydantic + pydantic-settings** for typed settings and models
- **APScheduler** for periodic refresh jobs
- **httpx** for HTTP requests
- **PyYAML** for YAML config

### 3.2 Data flow

1) Background fetch jobs pull from external sources (calendar/weather/transit/etc.)
2) Data is normalized to internal domain models
3) Normalized data is cached in SQLite with timestamps
4) UI reads cache and renders immediately (never blocks on external calls)

### 3.3 Design principles

- Adapters are **pluggable** and replaceable per provider
- UI is **cache-first**
- Failures are **isolated**: one widget failing does not break the whole page

---

## 4) Repository structure

Proposed layout:

- `pyproject.toml`
- `.env.example`
- `config/dashboard.yaml`
- `data/dashboard.db` (created at runtime)
- `photos/` (local pictures)
- `src/dashboard/` (application package)

Directory tree:

- `rpi-dashboard/`
  - `pyproject.toml`
  - `.env.example`
  - `config/`
    - `dashboard.yaml`
  - `data/`
    - `dashboard.db` (runtime)
  - `photos/`
    - `.gitkeep`
  - `src/`
    - `dashboard/`
      - `__init__.py`
      - `main.py`
      - `settings.py`
      - `scheduler.py`
      - `storage/`
        - `db.py`
        - `cache.py`
      - `domain/`
        - `models.py`
      - `adapters/`
        - `calendar/`
          - `base.py`
          - `google.py`
          - `ics.py`
          - `caldav.py`
          - `msgraph.py`
        - `weather/`
          - `base.py`
          - `open_meteo.py`
          - `metno.py`
        - `transit/`
          - `base.py`
          - `gtfs_rt.py`
          - `hafas.py`
        - `news/`
          - `base.py`
          - `rss.py`
        - `finance/`
          - `base.py`
          - `stooq.py`
          - `coingecko.py`
        - `sports/`
          - `base.py`
          - `thesportsdb.py`
          - `sportdataapi.py`
        - `photos/`
          - `local_folder.py`
        - `quotes/`
          - `base.py`
          - `quotable.py`
          - `on_this_day_wikipedia.py`
      - `web/`
        - `templates/`
          - `layout.html`
          - `dashboard.html`
          - `components/`
            - `tile_calendar.html`
            - `tile_weather.html`
            - `tile_transit.html`
            - `tile_news.html`
            - `tile_finance.html`
            - `tile_sports.html`
            - `tile_photo.html`
            - `tile_quote.html`
            - `modal.html`
        - `static/`
          - `app.css`
          - `app.js`

---

## 5) Packaging recommendation (choice 27e)

Use **uv** for environment + dependency management.

Rationale: fast, simple, good on Windows and Linux, deterministic resolution and lockfiles.

---

## 6) Configuration & secrets

You chose: **env vars for secrets** + **YAML for layout/non-secrets**.

### 6.1 `.env` (not committed)

Create a `.env` in the repo root (copy from `.env.example`):

Example keys (enable only what you use):

- `DASHBOARD_ENV=dev`
- `DASHBOARD_TIMEZONE=Europe/Berlin`

Calendars (examples):
- `GOOGLE_CALENDAR_API_KEY=...`
- `MSGRAPH_CLIENT_ID=...`
- `MSGRAPH_CLIENT_SECRET=...`
- `MSGRAPH_TENANT_ID=...`
- `CALDAV_URL=...`
- `CALDAV_USERNAME=...`
- `CALDAV_PASSWORD=...`

Weather (if provider needs it):
- `OPENWEATHER_API_KEY=...`

Transit:
- `GTFS_RT_URL=...`
- `HAFAS_ENDPOINT=...`

Sports/other:
- `SPORTS_API_KEY=...`

### 6.2 `config/dashboard.yaml` (committed)

Example configuration (edit to taste):

- `ui.title`: page title
- `ui.layout.left_column_width`: percent width
- `ui.layout.right_rotation_seconds`: how often the right panel changes
- `refresh.interval_minutes`: global refresh interval
- `location.mode`: `auto` or `fixed`
- `location.fallback_city`: used if auto fails
- `calendar.sources`: list of calendar adapters
- `transit.stop_name`: display name, provider may also require stop id
- `photos.folder`: local folder path

Example file content:

- `config/dashboard.yaml`:

  - ui:
    - title: "My Dashboard"
    - layout:
      - left_column_width: "30%"
      - right_rotation_seconds: 60
    - photo_rotation_seconds: 120
  - refresh:
    - interval_minutes: 10
    - jitter_seconds: 15
  - location:
    - mode: "auto"
    - fallback_city: "Berlin, DE"
  - calendar:
    - sources:
      - type: "google"
        - calendar_ids:
          - "primary"
      - type: "ics"
        - path: "config/personal.ics"
    - display:
      - range: "today"
      - show_time: true
      - show_title: true
  - weather:
    - provider: "open_meteo"
    - units: "metric"
    - show_daily_days: 5
  - transit:
    - provider: "gtfs_rt"
    - stop_name: "Alexanderplatz"
  - news:
    - provider: "rss"
    - feeds:
      - "https://www.tagesschau.de/xml/rss2"
      - "https://www.spiegel.de/international/index.rss"
    - max_items: 8
  - finance:
    - symbols:
      - stocks:
        - "AAPL"
        - "MSFT"
      - crypto:
        - "bitcoin"
        - "ethereum"
  - sports:
    - provider: "thesportsdb"
    - leagues:
      - "Bundesliga"
    - max_items: 6
  - photos:
    - folder: "photos"
    - extensions:
      - ".jpg"
      - ".jpeg"
      - ".png"
      - ".webp"
  - quotes:
    - provider: "quotable"

Note: YAML above is intentionally shown as a structured outline; implement as proper YAML with correct indentation.

---

## 7) Location “auto” strategy (weather)

Raspberry Pi usually has no GPS; “auto location” means:

1) Try IP-based geolocation (best-effort)
2) If it fails, use `location.fallback_city`

Implementation:
- `location/service.py` provides `get_location() -> (lat, lon, label)`
- Cache location for 24 hours to reduce external calls

---

## 8) Data sources (free-first, adapter-based)

### 8.1 Weather (free)

Recommended initial provider:
- **Open-Meteo** (often no API key required for basic forecasts)

Alternative:
- **met.no** (often free with usage guidelines)

Adapter interface:
- `get_weather(lat, lon) -> WeatherSnapshot`

### 8.2 Public transport in Germany

Because Germany is regional, implement two provider adapters:

1) `GTFS-RT` adapter (preferred if your local authority provides it)
2) `HAFAS` adapter (common for routing/departures in DE ecosystems)

Adapter interface:
- `get_departures(stop_query, horizon_minutes=60) -> list[Departure]`

### 8.3 News headlines

Use RSS feeds (simple, free):
- Adapter: `adapters/news/rss.py`
- Normalize to `Headline` objects

### 8.4 Finance (stocks + crypto)

- Crypto: CoinGecko-like free endpoints (rate limits apply)
- Stocks: Stooq-like delayed quotes (or any free provider you choose later)

Cache aggressively and show “delayed”/timestamped data.

### 8.5 Sports scores

Sports APIs vary. Keep it pluggable and cache results. The initial adapter can be a free source if available for your leagues.

### 8.6 Quotes / On this day

- Quotes: simple quote API (e.g., Quotable-style)
- “On this day”: Wikipedia-derived adapter (if stable endpoint is used)

---

## 9) Domain models (normalized)

All adapters must return Pydantic models defined in `src/dashboard/domain/models.py`.

Core models:

- `CalendarEvent`
  - fields: `title`, `start_dt`, `end_dt`, `all_day`, `source`
- `WeatherSnapshot`
  - fields: `temp`, `condition`, `daily: list[DailyForecast]`, `updated_at`
- `DailyForecast`
  - fields: `date`, `min_temp`, `max_temp`, `precip_prob`, `condition`
- `Departure`
  - fields: `line`, `destination`, `planned_time`, `realtime_time`, `platform`, `status`
- `Headline`
  - fields: `title`, `source`, `url`, `published_at`
- `FinanceQuote`
  - fields: `symbol`, `price`, `change`, `updated_at`
- `SportsResult`
  - fields: `league`, `home`, `away`, `score`, `start_time`, `status`
- `PhotoItem`
  - fields: `path`, `caption` (caption optional)
- `Quote`
  - fields: `text`, `author`, `source`

---

## 10) Caching layer (SQLite)

Use SQLite to cache JSON payloads keyed by widget.

Simplest schema:

- table `cache_entries`
  - `key` (TEXT PRIMARY KEY)
  - `json` (TEXT)
  - `fetched_at` (DATETIME)
  - `ttl_seconds` (INTEGER)

Example keys:

- `calendar.today`
- `weather.snapshot`
- `transit.departures`
- `news.headlines`
- `finance.quotes`
- `sports.scores`
- `quote.current`
- `photos.index`

UI reads cache and renders immediately. If data is missing, render a clear “no data yet” state.

---

## 11) Scheduler / refresh strategy

You chose: refresh every 5–15 minutes; default to 10.

Recommended job schedule:

- calendar: every 10 min
- weather: every 10 min
- transit: every 2–5 min (more time-sensitive)
- news: every 15 min
- finance: every 5–10 min
- sports: every 5–10 min
- quote: every 60 min
- photos folder scan: every 60 min

UI rotation (right side) is client-side:
- rotate every `ui.layout.right_rotation_seconds`

---

## 12) Web app routes (FastAPI)

Pages:
- `GET /` renders the dashboard
- `GET /health` returns JSON with service status + last refresh timestamps

Partials (for HTMX):
- `GET /partials/calendar`
- `GET /partials/weather`
- `GET /partials/transit`
- `GET /partials/news`
- `GET /partials/finance`
- `GET /partials/sports`
- `GET /partials/photo`
- `GET /partials/quote`

Modals:
- `GET /modals/{widget_name}` returns expanded HTML for that widget

---

## 13) Frontend behavior

No heavy framework. Use:

- CSS Grid for layout
- HTMX for partial updates and click-to-expand modals
- minimal JS for:
  - rotating right-side panels
  - rotating photos
  - optionally triggering periodic partial reloads (if desired)

Dense “control room” styling guidelines:

- emphasize key numbers with larger text
- secondary lines small but readable
- consistent tile sizing
- show timestamps (“updated 12:34”) per tile

---

## 14) Logging

Basic console logging only:

- Use Python `logging`
- default INFO level
- in dev: DEBUG optionally

On Raspberry Pi, if run as a systemd service, logs are captured by journal.

---

## 15) Local development (Windows) setup

### 15.1 Create the project

- Create folder `rpi-dashboard`
- Initialize with uv
- Add dependencies
- Start dev server

Commands (example):

- `uv init`
- add dependencies:
  - fastapi
  - uvicorn
  - jinja2
  - pydantic
  - pydantic-settings
  - python-dotenv
  - httpx
  - apscheduler
  - pyyaml
  - aiosqlite
  - feedparser

Run:

- `uv run uvicorn dashboard.main:app --reload --port 8000`

Open:

- `http://localhost:8000`

---

## 16) Raspberry Pi deployment plan (later)

Target deployment steps:

1) Install OS + updates
2) Install uv + dependencies
3) Clone repo
4) Create `.env`
5) Run server as systemd service
6) Start Chromium in kiosk mode to display dashboard

### 16.1 systemd service (server)

Example `/etc/systemd/system/dashboard.service`:

- Unit:
  - after network-online
- Service:
  - working directory `/home/pi/rpi-dashboard`
  - environment file `.env`
  - exec start: `uv run uvicorn dashboard.main:app --host 127.0.0.1 --port 8000`
  - restart always
  - user pi
- Install:
  - wanted by multi-user

Enable and start:

- `sudo systemctl daemon-reload`
- `sudo systemctl enable dashboard.service`
- `sudo systemctl start dashboard.service`

### 16.2 Chromium kiosk autostart

Command:

- `chromium-browser --kiosk --incognito --noerrdialogs --disable-infobars http://localhost:8000`

Add to desktop autostart depending on Pi desktop environment.

---

## 17) Privacy / security (sensitive calendar titles)

Minimum recommended controls:

- Bind server to `127.0.0.1` by default on the Pi (local-only)
- If you later want LAN access, add one of:
  - simple HTTP basic auth
  - reverse proxy with auth
  - firewall restrictions

Optional feature:
- “Privacy mode” that hides calendar titles (shows “busy”) unless expanded.

---

## 18) Testing strategy

- Unit tests for adapters with mocked HTTP responses
- Cache layer tests (write/read, TTL behavior)
- “Dev mode” stub adapters:
  - deterministic sample data for each widget
  - enables UI work without API keys

---

## 19) Build order (implementation checklist)

1) FastAPI skeleton + templates + static assets
2) Settings loader (.env + YAML) and validation
3) SQLite cache table + helper functions
4) Scheduler + one dummy refresh job
5) Dashboard layout (left fixed + right rotating panels)
6) Modal component + click-to-expand behavior
7) Weather adapter (Open-Meteo first) + tile
8) Local photos adapter + tile + rotation
9) Calendar adapters (start with easiest one you have) + tile
10) Transit adapter for your German stop + tile
11) RSS news adapter + tile
12) Finance adapter + tile
13) Sports adapter + tile
14) Quotes / on-this-day adapter + tile
15) Polish: timestamps, error states, loading states
16) Pi kiosk deployment scripts/docs

---

## 20) Open decisions intentionally left configurable

Not specified yet, so left flexible by adapter/config:

- exact calendar providers used first (Google vs CalDAV vs ICS vs MS Graph)
- which German transit backend and stop identifier format
- finance quote provider specifics and rate limits
- sports data provider specifics
- exact panel rotation timings and ordering

The adapter architecture ensures you can finalize these later with minimal refactor.

---

## 21) Definition of done

The project is done when:

- Running locally: `http://localhost:8000` shows the dashboard
- Dashboard shows:
  - Today’s calendar events (multi-source)
  - Weather current + daily forecast (auto location fallback)
  - Next departures for a configured German stop/station
  - Rotating right-side panels: news, finance, sports, photos, quote/on-this-day
- Data refresh occurs automatically on the configured cadence
- Clicking/tapping any tile opens an expanded modal view
- The app can be deployed on a Raspberry Pi and displayed in Chromium kiosk mode

---

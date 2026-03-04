# Raspberry Pi Dashboard (Steps 1-14 Baseline)

Local-first dashboard app built with FastAPI + Jinja templates.

This repository currently includes:
- FastAPI server skeleton
- Typed settings loader (`.env` + `config/dashboard.yaml`) with validation
- SQLite cache table + helper functions
- APScheduler integration with a dummy refresh job
- Dashboard layout with fixed left column + rotating right panels
- Modal component with click-to-expand behavior
- Weather refresh job using Open-Meteo with IP-based auto location + fallback city
- Weather tile rendering current conditions and daily forecast from cache
- Local photos adapter (folder scan) with cached index, photo tile rendering, and client-side slide rotation
- Calendar adapter (ICS file + URL sources) with cached today-events and calendar tile rendering
- Transit adapter (`transport.rest`) with cached departures and transit tile rendering
- RSS news adapter with cached headlines, tile rendering, and expanded modal view
- Finance adapter (`stooq + coingecko`) with cached quotes, tile rendering, and expanded modal view
- Sports adapter (`thesportsdb`) with cached scores/fixtures, tile rendering, and expanded modal view
- Quote + on-this-day adapters (`quotable` + `wikipedia`) with cached data, tile rendering, and expanded modal view

## Quick Start (Windows / PowerShell)

1. Install `uv` (if not already installed):

```powershell
powershell -ExecutionPolicy Bypass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

2. In this project folder, install dependencies:

```powershell
uv sync
```

3. Run the app:

```powershell
uv run uvicorn dashboard.main:app --reload --app-dir src --port 8000
```

4. Open:

`http://127.0.0.1:8000`

Health check:

`http://127.0.0.1:8000/health`

## Useful Files

- App entrypoint: `src/dashboard/main.py`
- Settings loader: `src/dashboard/settings.py`
- Scheduler: `src/dashboard/scheduler.py`
- SQLite helpers: `src/dashboard/storage/`
- Templates: `src/dashboard/web/templates/`
- Static assets: `src/dashboard/web/static/`
- Config stub: `config/dashboard.yaml`

## Calendar (ICS) Setup

Add one or more ICS sources in `config/dashboard.yaml`:

```yaml
calendar:
  sources:
    - type: "ics"
      path: "config/personal.ics"
      name: "Personal"
    - type: "ics_url"
      url: "https://pXX-caldav.icloud.com/published/2/abc123.../calendar.ics"
      name: "Apple (Read-Only)"
  display:
    range: "today"
    show_time: true
    show_title: true
```

Notes:
- `path` is resolved from the project root when relative.
- `url` must be an absolute `http` or `https` address.
- `webcal://...` links are accepted and normalized to `https://...`.
- Apple iCloud "Public Calendar" links work with `type: "ics_url"`.
- The dashboard currently renders events overlapping the local "today" range.

### Keep URL Private

If your calendar URL should not be committed:

1. Create `.env` from `.env.example` (already gitignored) and set:
   `DASHBOARD_CONFIG_PATH=config/dashboard.local.yaml`
2. Create `config/dashboard.local.yaml` with your private `ics_url` sources.
3. Keep `config/dashboard.yaml` free of secrets.

`config/*.local.yaml` is ignored by git in this repo.

## Transit Setup

Configure the German transit stop in `config/dashboard.yaml`:

```yaml
transit:
  provider: "transport_rest"
  stop_name: "Alexanderplatz"
  stop_id: "900100003"
  horizon_minutes: 60
  max_departures: 8
  transport_rest_base_url: "https://v6.vbb.transport.rest"
  transport_rest_fallback_base_urls:
    - "https://v6.db.transport.rest"
```

Notes:
- `stop_name` is used for stop lookup when `stop_id` is empty.
- Set `stop_id` if you want to avoid stop lookup on each refresh.
- `horizon_minutes` controls how far ahead departures are requested.
- `transport_rest_fallback_base_urls` is optional and should only include compatible network endpoints.
- If the provider is temporarily unavailable, the dashboard keeps showing the last cached departures.

## News (RSS) Setup

Configure RSS feeds in `config/dashboard.yaml`:

```yaml
news:
  provider: "rss"
  feeds:
    - "https://www.tagesschau.de/xml/rss2"
    - "https://www.spiegel.de/international/index.rss"
  max_items: 8
```

Notes:
- `feeds` entries must be absolute `http` or `https` URLs.
- Headlines are refreshed every 15 minutes and cached in SQLite.
- Open headline links from the tile or modal (opens a new tab/window).

## Finance Setup

Configure stocks and crypto symbols in `config/dashboard.yaml`:

```yaml
finance:
  provider: "stooq_coingecko"
  symbols:
    stocks:
      - "AAPL"
      - "MSFT"
    crypto:
      - "bitcoin"
      - "ethereum"
  max_items: 8
```

Notes:
- Stocks are pulled from Stooq and crypto prices from CoinGecko (USD).
- Finance refresh runs every 5-10 minutes (derived from global refresh interval).
- If a provider fails, the dashboard keeps showing last cached quotes and marks them stale.

## Sports Setup

Configure sports leagues in `config/dashboard.yaml`:

```yaml
sports:
  provider: "thesportsdb"
  sport: "Soccer"
  leagues:
    - "Bundesliga"
  max_items: 6
```

Optional `.env` key:

```dotenv
SPORTS_API_KEY=3
```

Notes:
- `leagues` accepts names (for example `Bundesliga`) or explicit IDs via `id:<league_id>`.
- Sports refresh runs every 5-10 minutes (derived from global refresh interval).
- If the provider fails, the dashboard keeps showing last cached scores and marks them stale.

## Quotes / On-This-Day Setup

Configure quote and on-this-day providers in `config/dashboard.yaml`:

```yaml
quotes:
  provider: "quotable"
  on_this_day_provider: "wikipedia"
  max_on_this_day_items: 3
```

Notes:
- Quote refresh runs every 60 minutes.
- The quote adapter tries Quotable first, then falls back to ZenQuotes if needed.
- On-this-day entries are fetched from Wikipedia endpoints and cached with the quote payload.
- If providers fail, the dashboard keeps showing last cached quote/on-this-day data and marks it stale.

## Current Status

Steps 1-14 from `project.md` are implemented:
1. FastAPI skeleton + templates + static assets
2. Settings loader (`.env` + YAML) and validation
3. SQLite cache table + helper functions
4. Scheduler + one dummy refresh job
5. Dashboard layout (left fixed + right rotating panels)
6. Modal component + click-to-expand behavior
7. Weather adapter (Open-Meteo first) + tile
8. Local photos adapter + tile + rotation
9. Calendar adapter (ICS first) + tile
10. Transit adapter for German stop + tile
11. RSS news adapter + tile
12. Finance adapter + tile
13. Sports adapter + tile
14. Quotes / on-this-day adapter + tile

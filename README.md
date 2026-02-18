# Raspberry Pi Dashboard (Steps 1-9 Baseline)

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

## Current Status

Steps 1-9 from `project.md` are implemented:
1. FastAPI skeleton + templates + static assets
2. Settings loader (`.env` + YAML) and validation
3. SQLite cache table + helper functions
4. Scheduler + one dummy refresh job
5. Dashboard layout (left fixed + right rotating panels)
6. Modal component + click-to-expand behavior
7. Weather adapter (Open-Meteo first) + tile
8. Local photos adapter + tile + rotation
9. Calendar adapter (ICS first) + tile

# Raspberry Pi Dashboard (Step 1 Scaffold)

Local-first dashboard app built with FastAPI + Jinja templates.

This repository currently includes:
- FastAPI server skeleton
- Dashboard page + tile templates
- Static CSS/JS assets
- Placeholder partial and modal routes

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
- Templates: `src/dashboard/web/templates/`
- Static assets: `src/dashboard/web/static/`
- Config stub: `config/dashboard.yaml`

## Current Status

Only step 1 from `project.md` is implemented so far (skeleton + templates + static assets).


from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .adapters.calendar import CalendarAdapterError, IcsCalendarAdapter, RemoteIcsCalendarAdapter
from .adapters.photos import LocalFolderPhotosAdapter, PhotosAdapterError
from .adapters.weather import OpenMeteoWeatherAdapter, WeatherAdapterError
from .domain.models import CalendarEvent
from .location.service import LocationResolutionError, get_location
from .settings import AppSettings
from .storage.cache import set_cache_entry

LOGGER = logging.getLogger(__name__)

DUMMY_REFRESH_CACHE_KEY = "system.dummy_refresh"
CALENDAR_REFRESH_CACHE_KEY = "calendar.today"
WEATHER_REFRESH_CACHE_KEY = "weather.snapshot"
PHOTOS_REFRESH_CACHE_KEY = "photos.index"
PHOTOS_SCAN_INTERVAL_MINUTES = 60


def run_dummy_refresh_job(settings: AppSettings) -> None:
    refreshed_at = datetime.now(timezone.utc)
    payload = {
        "status": "ok",
        "message": "Dummy refresh completed successfully.",
        "refreshed_at_utc": refreshed_at.isoformat(),
    }
    ttl_seconds = max(settings.yaml.refresh.interval_minutes * 120, 60)
    set_cache_entry(
        settings.db_path,
        DUMMY_REFRESH_CACHE_KEY,
        payload,
        ttl_seconds=ttl_seconds,
        fetched_at=refreshed_at,
    )
    LOGGER.info("Dummy refresh job updated '%s' at %s", DUMMY_REFRESH_CACHE_KEY, refreshed_at)


def _build_weather_adapter(settings: AppSettings) -> OpenMeteoWeatherAdapter:
    provider = settings.yaml.weather.provider
    if provider != "open_meteo":
        raise ValueError(f"Unsupported weather provider: {provider}")
    return OpenMeteoWeatherAdapter(
        units=settings.yaml.weather.units,
        timezone_name=settings.env.dashboard_timezone,
    )


def _build_photos_adapter(settings: AppSettings) -> LocalFolderPhotosAdapter:
    return LocalFolderPhotosAdapter(
        folder=settings.photos_path,
        extensions=settings.yaml.photos.extensions,
    )


def _build_calendar_adapters(settings: AppSettings) -> list[IcsCalendarAdapter | RemoteIcsCalendarAdapter]:
    adapters: list[IcsCalendarAdapter | RemoteIcsCalendarAdapter] = []
    for source in settings.yaml.calendar.sources:
        if source.type == "ics":
            if source.path is None:
                raise ValueError("calendar source path was missing for type 'ics'")

            source_path = source.path
            if not source_path.is_absolute():
                source_path = (settings.project_root / source_path).resolve()

            adapters.append(
                IcsCalendarAdapter(
                    path=source_path,
                    timezone_name=settings.env.dashboard_timezone,
                    source_name=source.name,
                )
            )
            continue

        if source.type == "ics_url":
            if source.url is None:
                raise ValueError("calendar source url was missing for type 'ics_url'")
            adapters.append(
                RemoteIcsCalendarAdapter(
                    url=source.url,
                    timezone_name=settings.env.dashboard_timezone,
                    source_name=source.name,
                )
            )
            continue

        raise ValueError(f"Unsupported calendar source type: {source.type}")
    return adapters


def run_calendar_refresh_job(settings: AppSettings) -> None:
    refreshed_at = datetime.now(timezone.utc)
    target_date = datetime.now(settings.timezone).date()
    events: list[CalendarEvent] = []
    source_names: list[str] = []
    errors: list[str] = []

    try:
        adapters = _build_calendar_adapters(settings)
    except (CalendarAdapterError, ValueError):
        LOGGER.exception("Calendar refresh job configuration failed")
        adapters = []

    for adapter in adapters:
        source_names.append(adapter.source_name)
        try:
            source_events = adapter.get_events_for_day(target_date)
        except CalendarAdapterError as exc:
            LOGGER.warning("Calendar source '%s' failed: %s", adapter.source_name, exc)
            errors.append(f"{adapter.source_name}: {exc}")
            continue
        except Exception:  # pragma: no cover - defensive fallback
            LOGGER.exception("Calendar source '%s' failed", adapter.source_name)
            errors.append(f"{adapter.source_name}: unexpected error")
            continue
        events.extend(source_events)

    events.sort(key=lambda event: (event.start_dt, event.title.lower(), event.source.lower()))
    payload = {
        "range": settings.yaml.calendar.display.range,
        "target_date": target_date.isoformat(),
        "timezone": settings.env.dashboard_timezone,
        "source_count": len(adapters),
        "sources": source_names,
        "error_count": len(errors),
        "errors": errors,
        "count": len(events),
        "refreshed_at_utc": refreshed_at.isoformat(),
        "events": [event.model_dump(mode="json") for event in events],
    }
    ttl_seconds = max(settings.yaml.refresh.interval_minutes * 120, 300)
    set_cache_entry(
        settings.db_path,
        CALENDAR_REFRESH_CACHE_KEY,
        payload,
        ttl_seconds=ttl_seconds,
        fetched_at=refreshed_at,
    )
    LOGGER.info("Calendar refresh job updated '%s' at %s", CALENDAR_REFRESH_CACHE_KEY, refreshed_at)


def run_weather_refresh_job(settings: AppSettings) -> None:
    refreshed_at = datetime.now(timezone.utc)
    try:
        lat, lon, label = get_location(settings)
        adapter = _build_weather_adapter(settings)
        snapshot = adapter.get_weather(
            lat,
            lon,
            days=settings.yaml.weather.show_daily_days,
        )
    except (LocationResolutionError, WeatherAdapterError, ValueError):
        LOGGER.exception("Weather refresh job failed")
        return
    except Exception:  # pragma: no cover - defensive fallback
        LOGGER.exception("Weather refresh job failed")
        return

    payload = {
        "provider": settings.yaml.weather.provider,
        "units": settings.yaml.weather.units,
        "location_label": label,
        "lat": lat,
        "lon": lon,
        "refreshed_at_utc": refreshed_at.isoformat(),
        "snapshot": snapshot.model_dump(mode="json"),
    }
    ttl_seconds = max(settings.yaml.refresh.interval_minutes * 120, 300)
    set_cache_entry(
        settings.db_path,
        WEATHER_REFRESH_CACHE_KEY,
        payload,
        ttl_seconds=ttl_seconds,
        fetched_at=refreshed_at,
    )
    LOGGER.info("Weather refresh job updated '%s' at %s", WEATHER_REFRESH_CACHE_KEY, refreshed_at)


def run_photos_refresh_job(settings: AppSettings) -> None:
    refreshed_at = datetime.now(timezone.utc)
    try:
        adapter = _build_photos_adapter(settings)
        photos = adapter.get_photos()
    except PhotosAdapterError:
        LOGGER.exception("Photos refresh job failed")
        return
    except Exception:  # pragma: no cover - defensive fallback
        LOGGER.exception("Photos refresh job failed")
        return

    payload = {
        "folder": str(settings.photos_path),
        "extensions": settings.yaml.photos.extensions,
        "refreshed_at_utc": refreshed_at.isoformat(),
        "count": len(photos),
        "items": [photo.model_dump(mode="json") for photo in photos],
    }
    ttl_seconds = max(PHOTOS_SCAN_INTERVAL_MINUTES * 120, 3600)
    set_cache_entry(
        settings.db_path,
        PHOTOS_REFRESH_CACHE_KEY,
        payload,
        ttl_seconds=ttl_seconds,
        fetched_at=refreshed_at,
    )
    LOGGER.info("Photos refresh job updated '%s' at %s", PHOTOS_REFRESH_CACHE_KEY, refreshed_at)


def build_scheduler(settings: AppSettings) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=settings.timezone)
    scheduler.add_job(
        run_dummy_refresh_job,
        "interval",
        kwargs={"settings": settings},
        minutes=settings.yaml.refresh.interval_minutes,
        jitter=settings.yaml.refresh.jitter_seconds,
        id="dummy_refresh_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_calendar_refresh_job,
        "interval",
        kwargs={"settings": settings},
        minutes=settings.yaml.refresh.interval_minutes,
        jitter=settings.yaml.refresh.jitter_seconds,
        id="calendar_refresh_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        run_weather_refresh_job,
        "interval",
        kwargs={"settings": settings},
        minutes=settings.yaml.refresh.interval_minutes,
        jitter=settings.yaml.refresh.jitter_seconds,
        id="weather_refresh_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        run_photos_refresh_job,
        "interval",
        kwargs={"settings": settings},
        minutes=PHOTOS_SCAN_INTERVAL_MINUTES,
        jitter=settings.yaml.refresh.jitter_seconds,
        id="photos_refresh_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    return scheduler

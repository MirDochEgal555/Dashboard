from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .adapters.calendar import CalendarAdapterError, IcsCalendarAdapter, RemoteIcsCalendarAdapter
from .adapters.photos import LocalFolderPhotosAdapter, PhotosAdapterError
from .adapters.transit import TransitAdapterError, TransportRestTransitAdapter
from .adapters.weather import OpenMeteoWeatherAdapter, WeatherAdapterError
from .domain.models import CalendarEvent
from .location.service import LocationResolutionError, get_location
from .settings import AppSettings
from .storage.cache import get_cache_entry, set_cache_entry

LOGGER = logging.getLogger(__name__)

DUMMY_REFRESH_CACHE_KEY = "system.dummy_refresh"
CALENDAR_REFRESH_CACHE_KEY = "calendar.today"
WEATHER_REFRESH_CACHE_KEY = "weather.snapshot"
TRANSIT_REFRESH_CACHE_KEY = "transit.departures"
PHOTOS_REFRESH_CACHE_KEY = "photos.index"
PHOTOS_SCAN_INTERVAL_MINUTES = 60
TRANSIT_MIN_REFRESH_INTERVAL_MINUTES = 2
TRANSIT_MAX_REFRESH_INTERVAL_MINUTES = 5


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


def _build_transit_adapter(settings: AppSettings) -> TransportRestTransitAdapter:
    provider = settings.yaml.transit.provider
    if provider != "transport_rest":
        raise ValueError(f"Unsupported transit provider: {provider}")
    return TransportRestTransitAdapter(
        base_url=settings.yaml.transit.transport_rest_base_url,
        fallback_base_urls=tuple(settings.yaml.transit.transport_rest_fallback_base_urls),
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


def _transit_refresh_interval_minutes(settings: AppSettings) -> int:
    return min(
        TRANSIT_MAX_REFRESH_INTERVAL_MINUTES,
        max(TRANSIT_MIN_REFRESH_INTERVAL_MINUTES, settings.yaml.refresh.interval_minutes),
    )


def _transit_ttl_seconds(settings: AppSettings) -> int:
    return max(_transit_refresh_interval_minutes(settings) * 120, 180)


def run_transit_refresh_job(settings: AppSettings) -> None:
    refreshed_at = datetime.now(timezone.utc)
    configured_stop_name = settings.yaml.transit.stop_name
    configured_stop_id = settings.yaml.transit.stop_id
    ttl_seconds = _transit_ttl_seconds(settings)

    try:
        adapter = _build_transit_adapter(settings)
        resolved_stop_id = configured_stop_id
        resolved_stop_name = configured_stop_name
        if not resolved_stop_id:
            resolved_stop_id, resolved_stop_name = adapter.resolve_stop(configured_stop_name)

        departures = adapter.get_departures(
            resolved_stop_id,
            horizon_minutes=settings.yaml.transit.horizon_minutes,
            limit=settings.yaml.transit.max_departures,
        )
    except (TransitAdapterError, ValueError) as exc:
        existing_entry = get_cache_entry(settings.db_path, TRANSIT_REFRESH_CACHE_KEY)
        existing_payload = existing_entry.payload if existing_entry and isinstance(existing_entry.payload, dict) else None

        fallback_departures = []
        fallback_stop_name = configured_stop_name
        fallback_stop_id = configured_stop_id
        if existing_payload is not None:
            departures_payload = existing_payload.get("departures")
            if isinstance(departures_payload, list):
                fallback_departures = departures_payload
            cached_stop_name = existing_payload.get("stop_name")
            if isinstance(cached_stop_name, str) and cached_stop_name.strip():
                fallback_stop_name = cached_stop_name.strip()
            cached_stop_id = existing_payload.get("stop_id")
            if isinstance(cached_stop_id, str) and cached_stop_id.strip():
                fallback_stop_id = cached_stop_id.strip()

        payload = {
            "provider": settings.yaml.transit.provider,
            "base_url": settings.yaml.transit.transport_rest_base_url,
            "configured_stop_name": configured_stop_name,
            "configured_stop_id": configured_stop_id,
            "stop_name": fallback_stop_name,
            "stop_id": fallback_stop_id,
            "horizon_minutes": settings.yaml.transit.horizon_minutes,
            "max_departures": settings.yaml.transit.max_departures,
            "refreshed_at_utc": (
                existing_payload.get("refreshed_at_utc")
                if isinstance(existing_payload, dict)
                else None
            ),
            "count": len(fallback_departures),
            "departures": fallback_departures,
            "last_error": str(exc),
            "last_error_at_utc": refreshed_at.isoformat(),
        }
        set_cache_entry(
            settings.db_path,
            TRANSIT_REFRESH_CACHE_KEY,
            payload,
            ttl_seconds=ttl_seconds,
            fetched_at=(existing_entry.fetched_at if existing_entry is not None else refreshed_at),
        )
        LOGGER.warning("Transit refresh failed; using cached data when available: %s", exc)
        return
    except Exception:  # pragma: no cover - defensive fallback
        LOGGER.exception("Transit refresh job failed")
        return

    payload = {
        "provider": settings.yaml.transit.provider,
        "base_url": settings.yaml.transit.transport_rest_base_url,
        "configured_stop_name": configured_stop_name,
        "configured_stop_id": configured_stop_id,
        "stop_name": resolved_stop_name,
        "stop_id": resolved_stop_id,
        "horizon_minutes": settings.yaml.transit.horizon_minutes,
        "max_departures": settings.yaml.transit.max_departures,
        "refreshed_at_utc": refreshed_at.isoformat(),
        "count": len(departures),
        "departures": [departure.model_dump(mode="json") for departure in departures],
        "last_error": None,
        "last_error_at_utc": None,
    }
    set_cache_entry(
        settings.db_path,
        TRANSIT_REFRESH_CACHE_KEY,
        payload,
        ttl_seconds=ttl_seconds,
        fetched_at=refreshed_at,
    )
    LOGGER.info("Transit refresh job updated '%s' at %s", TRANSIT_REFRESH_CACHE_KEY, refreshed_at)


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
        run_transit_refresh_job,
        "interval",
        kwargs={"settings": settings},
        minutes=_transit_refresh_interval_minutes(settings),
        jitter=settings.yaml.refresh.jitter_seconds,
        id="transit_refresh_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=90,
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

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .settings import AppSettings
from .storage.cache import set_cache_entry

LOGGER = logging.getLogger(__name__)

DUMMY_REFRESH_CACHE_KEY = "system.dummy_refresh"


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
    return scheduler

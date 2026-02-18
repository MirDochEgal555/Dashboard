from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class UiLayoutSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    left_column_width: str = Field(default="30%")
    right_rotation_seconds: int = Field(default=60, ge=5, le=3600)

    @field_validator("left_column_width")
    @classmethod
    def validate_left_column_width(cls, value: str) -> str:
        text = value.strip()
        if not text.endswith("%"):
            raise ValueError("ui.layout.left_column_width must be a percentage string like '30%'")
        try:
            percent = float(text[:-1])
        except ValueError as exc:
            raise ValueError(
                "ui.layout.left_column_width must be a numeric percentage like '30%'"
            ) from exc
        if percent <= 0 or percent >= 100:
            raise ValueError("ui.layout.left_column_width must be between 0% and 100%")
        return f"{percent:g}%"


class UiSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = "My Dashboard"
    layout: UiLayoutSettings = Field(default_factory=UiLayoutSettings)
    photo_rotation_seconds: int = Field(default=120, ge=5, le=3600)


class RefreshSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    interval_minutes: int = Field(default=10, ge=1, le=60)
    jitter_seconds: int = Field(default=15, ge=0, le=300)


class LocationSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: Literal["auto", "fixed"] = "auto"
    fallback_city: str = "Stuttgart, DE"

    @field_validator("fallback_city")
    @classmethod
    def validate_fallback_city(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("location.fallback_city must not be empty")
        return text


class CalendarDisplaySettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    range: Literal["today"] = "today"
    show_time: bool = True
    show_title: bool = True


class CalendarIcsSourceSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    type: Literal["ics", "ics_url"] = "ics"
    path: Path | None = None
    url: str | None = None
    name: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("calendar.sources[].path must not be empty")
        return Path(text)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            raise ValueError("calendar.sources[].url must not be empty")

        parsed = urlparse(text)
        if parsed.scheme == "webcal":
            text = parsed._replace(scheme="https").geturl()
            parsed = urlparse(text)

        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("calendar.sources[].url must be an absolute http(s) URL")
        return text

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @model_validator(mode="after")
    def validate_source_fields(self) -> CalendarIcsSourceSettings:
        if self.type == "ics":
            if self.path is None:
                raise ValueError("calendar.sources[].path is required when type is 'ics'")
            if self.url is not None:
                raise ValueError("calendar.sources[].url is not allowed when type is 'ics'")
            return self

        if self.type == "ics_url":
            if self.url is None:
                raise ValueError("calendar.sources[].url is required when type is 'ics_url'")
            if self.path is not None:
                raise ValueError("calendar.sources[].path is not allowed when type is 'ics_url'")
            return self

        raise ValueError(f"Unsupported calendar source type: {self.type}")


class CalendarSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sources: list[CalendarIcsSourceSettings] = Field(default_factory=list)
    display: CalendarDisplaySettings = Field(default_factory=CalendarDisplaySettings)


class WeatherSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: Literal["open_meteo"] = "open_meteo"
    units: Literal["metric", "imperial"] = "metric"
    show_daily_days: int = Field(default=5, ge=1, le=10)


class PhotosSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    folder: Path = Path("photos")
    extensions: list[str] = Field(default_factory=lambda: [".jpg", ".jpeg", ".png", ".webp"])

    @field_validator("folder")
    @classmethod
    def validate_folder(cls, value: Path) -> Path:
        text = str(value).strip()
        if not text:
            raise ValueError("photos.folder must not be empty")
        return Path(text)

    @field_validator("extensions")
    @classmethod
    def validate_extensions(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw_extension in values:
            if not isinstance(raw_extension, str):
                raise ValueError("photos.extensions entries must be strings")
            extension = raw_extension.strip().lower()
            if not extension:
                raise ValueError("photos.extensions entries must not be empty")
            if not extension.startswith("."):
                extension = f".{extension}"
            normalized.append(extension)

        deduplicated = list(dict.fromkeys(normalized))
        if not deduplicated:
            raise ValueError("photos.extensions must contain at least one extension")
        return deduplicated


class DashboardYamlSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ui: UiSettings = Field(default_factory=UiSettings)
    refresh: RefreshSettings = Field(default_factory=RefreshSettings)
    location: LocationSettings = Field(default_factory=LocationSettings)
    calendar: CalendarSettings = Field(default_factory=CalendarSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)
    photos: PhotosSettings = Field(default_factory=PhotosSettings)


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    dashboard_env: Literal["dev", "test", "prod"] = "dev"
    dashboard_timezone: str = "Europe/Berlin"
    dashboard_config_path: Path = Path("config/dashboard.yaml")
    dashboard_db_path: Path = Path("data/dashboard.db")

    @field_validator("dashboard_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown timezone: {value}") from exc
        return value


class AppSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    env: EnvSettings
    yaml: DashboardYamlSettings
    project_root: Path
    config_path: Path
    db_path: Path
    photos_path: Path
    timezone: ZoneInfo


def _resolve_project_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    return (PROJECT_ROOT / path).resolve()


def _load_yaml_settings(path: Path) -> DashboardYamlSettings:
    if not path.exists():
        raise FileNotFoundError(f"Dashboard config file not found: {path}")

    raw_config = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise ValueError("Dashboard config must be a YAML mapping/object at the top level")
    return DashboardYamlSettings.model_validate(raw_config)


@lru_cache(maxsize=1)
def load_settings() -> AppSettings:
    env = EnvSettings()
    config_path = _resolve_project_path(env.dashboard_config_path)
    db_path = _resolve_project_path(env.dashboard_db_path)
    yaml_settings = _load_yaml_settings(config_path)
    photos_path = _resolve_project_path(yaml_settings.photos.folder)
    timezone = ZoneInfo(env.dashboard_timezone)
    return AppSettings(
        env=env,
        yaml=yaml_settings,
        project_root=PROJECT_ROOT,
        config_path=config_path,
        db_path=db_path,
        photos_path=photos_path,
        timezone=timezone,
    )

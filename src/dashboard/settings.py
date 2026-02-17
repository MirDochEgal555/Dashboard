from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
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


class WeatherSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider: Literal["open_meteo"] = "open_meteo"
    units: Literal["metric", "imperial"] = "metric"
    show_daily_days: int = Field(default=5, ge=1, le=10)


class DashboardYamlSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ui: UiSettings = Field(default_factory=UiSettings)
    refresh: RefreshSettings = Field(default_factory=RefreshSettings)
    location: LocationSettings = Field(default_factory=LocationSettings)
    weather: WeatherSettings = Field(default_factory=WeatherSettings)


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
    config_path: Path
    db_path: Path
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
    timezone = ZoneInfo(env.dashboard_timezone)
    return AppSettings(
        env=env,
        yaml=yaml_settings,
        config_path=config_path,
        db_path=db_path,
        timezone=timezone,
    )

from __future__ import annotations

from datetime import date, datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CalendarEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    start_dt: datetime
    end_dt: datetime
    all_day: bool = False
    source: str

    @field_validator("title", "source")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("calendar event text fields must not be empty")
        return text

    @model_validator(mode="after")
    def validate_time_range(self) -> CalendarEvent:
        if self.end_dt < self.start_dt:
            raise ValueError("calendar event end_dt must be >= start_dt")
        return self


class DailyForecast(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: date
    min_temp: float
    max_temp: float
    precip_prob: int | None = Field(default=None, ge=0, le=100)
    condition: str


class WeatherSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    temp: float
    condition: str
    daily: list[DailyForecast] = Field(default_factory=list)
    updated_at: datetime


class Departure(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line: str
    destination: str
    planned_time: datetime
    realtime_time: datetime | None = None
    platform: str | None = None
    status: str | None = None

    @field_validator("line", "destination")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("departure text fields must not be empty")
        return text

    @field_validator("platform", "status")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("planned_time", "realtime_time")
    @classmethod
    def normalize_datetime(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class PhotoItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    caption: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("photo path must not be empty")
        return text

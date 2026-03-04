from __future__ import annotations

from datetime import date, datetime, timezone
from urllib.parse import urlparse

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


class Headline(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    source: str
    url: str
    published_at: datetime

    @field_validator("title", "source")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("headline title/source must not be empty")
        return text

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        text = value.strip()
        parsed = urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("headline url must be an absolute http(s) URL")
        return text

    @field_validator("published_at")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class FinanceQuote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    price: float
    change: float | None = None
    updated_at: datetime

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("finance quote symbol must not be empty")
        return text

    @field_validator("updated_at")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SportsResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    league: str
    home: str
    away: str
    score: str
    start_time: datetime
    status: str

    @field_validator("league", "home", "away", "score", "status")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("sports result text fields must not be empty")
        return text

    @field_validator("start_time")
    @classmethod
    def normalize_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Quote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    author: str
    source: str

    @field_validator("text", "author", "source")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("quote text fields must not be empty")
        return text


class OnThisDayItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    year: int | None = None
    text: str
    source: str | None = None
    url: str | None = None

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("on-this-day text must not be empty")
        return text

    @field_validator("source")
    @classmethod
    def normalize_source(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        return text or None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = value.strip()
        if not text:
            return None
        parsed = urlparse(text)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("on-this-day url must be an absolute http(s) URL")
        return text


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

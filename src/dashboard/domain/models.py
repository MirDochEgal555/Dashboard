from __future__ import annotations

from datetime import date, datetime

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

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


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

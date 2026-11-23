from __future__ import annotations

from pydantic import BaseModel, Field


class TaskSchedulerSettingOut(BaseModel):
    enabled: bool
    crontab: str
    timezone: str
    openlist_cleanup_enabled: bool = False
    openlist_cleanup_path: str = ""
    openlist_cleanup_crontab: str = "0 3 * * *"


class TaskSchedulerSettingUpdateIn(BaseModel):
    enabled: bool | None = None
    crontab: str | None = Field(default=None, max_length=64)
    timezone: str | None = Field(default=None, max_length=64)
    openlist_cleanup_enabled: bool | None = None
    openlist_cleanup_path: str | None = Field(default=None, max_length=512)
    openlist_cleanup_crontab: str | None = Field(default=None, max_length=64)

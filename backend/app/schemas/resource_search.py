from __future__ import annotations

from pydantic import BaseModel, Field


class ResourceSearchSourceItemOut(BaseModel):
    key: str = Field(min_length=1, max_length=32)
    enabled: bool
    server: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, max_length=256)
    token: str | None = Field(default=None, max_length=2048)


class ResourceSearchSourceListOut(BaseModel):
    sources: list[ResourceSearchSourceItemOut] = []


class ResourceSearchSourceUpdateIn(BaseModel):
    enabled: bool | None = None
    server: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, max_length=256)
    token: str | None = Field(default=None, max_length=2048)


class TaskSuggestionItemOut(BaseModel):
    taskname: str = Field(default="", max_length=512)
    shareurl: str = Field(default="", max_length=2048)
    content: str | None = None
    datetime: str | None = None
    channel: str | None = None
    source: str | None = None
    source_key: str | None = None


class TaskSuggestionListOut(BaseModel):
    success: bool = True
    data: list[TaskSuggestionItemOut] = []
    message: str | None = None


class TaskSuggestionVerifyIn(BaseModel):
    shareurls: list[str] = Field(min_length=1, max_length=200)
    account_name: str | None = Field(default=None, max_length=128)


class TaskSuggestionVerifyItemOut(BaseModel):
    shareurl: str
    drive_type: str | None = None
    ok: bool = False
    message: str | None = None
    pdir_fid: str | None = None
    max_file_size: int | None = None
    latest_video: dict | None = None
    is_largest: bool = False


class TaskSuggestionVerifyOut(BaseModel):
    items: list[TaskSuggestionVerifyItemOut] = []
    total: int = 0
    valid: int = 0
    invalid: int = 0

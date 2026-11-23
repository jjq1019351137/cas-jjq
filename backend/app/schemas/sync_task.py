from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


SyncEndpointType = Literal["local", "openlist", "netdisk"]
SyncMode = Literal["one_way", "two_way"]


class SyncEndpoint(BaseModel):
    type: SyncEndpointType
    path: str = Field(min_length=1)
    account_id: int | None = None
    account_name: str | None = None
    drive_type: str | None = None


class SyncStrategy(BaseModel):
    overwrite: bool = False
    one_way_delete_extras: bool = False
    # 单向删除多余文件延时（分钟）：0/5/10/15/20/25/30，0 表示同步完成后立即删除
    one_way_delete_extras_delay_minutes: int = Field(default=0, ge=0, le=30)

    @field_validator("one_way_delete_extras_delay_minutes", mode="before")
    @classmethod
    def _coerce_delete_delay(cls, value: object) -> int:
        try:
            raw = int(value or 0)
        except Exception:
            return 0
        if raw <= 0:
            return 0
        allowed = (5, 10, 15, 20, 25, 30)
        for item in allowed:
            if raw <= item:
                return item
        return 30
    force_refresh: bool = False
    concurrency: int = Field(default=4, ge=1, le=32)
    request_interval_seconds: float = Field(default=0.0, ge=0.0, le=5.0)
    openlist_copy_batch_size: int = Field(default=200, ge=1, le=5000)
    # 同步 .zip 后：在目标目录解压 → 按 zip 前缀重命名 → 删除 zip
    unzip_zip_after_sync: bool = True
    # 自动洗码：仅当目标网盘为移动云盘(cloud139)时生效。上传后检测文件是否被和谐，
    auto_wash: bool = True


class SyncTaskBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    enabled: bool = True
    source: SyncEndpoint
    target: SyncEndpoint
    mode: SyncMode = "one_way"
    strategy: SyncStrategy = Field(default_factory=SyncStrategy)
    drama_task_uids: list[str] = Field(default_factory=list)
    addition: dict[str, Any] = Field(default_factory=dict)


class SyncTaskCreateIn(SyncTaskBase):
    pass


class SyncTaskUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    enabled: bool | None = None
    source: SyncEndpoint | None = None
    target: SyncEndpoint | None = None
    mode: SyncMode | None = None
    strategy: SyncStrategy | None = None
    drama_task_uids: list[str] | None = None
    addition: dict[str, Any] | None = None


class SyncExecutionOut(BaseModel):
    id: int
    sync_task_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    stage: str | None = None
    run_log: str | None = None
    stats: dict[str, Any] = {}
    message: str | None = None
    cancel_requested_at: datetime | None = None
    cancel_requested_by: int | None = None
    cancel_message: str | None = None


class SyncTaskOut(BaseModel):
    id: int
    uid: str
    name: str
    enabled: bool
    source: SyncEndpoint
    target: SyncEndpoint
    mode: SyncMode
    strategy: SyncStrategy
    drama_task_uids: list[str] = Field(default_factory=list)
    addition: dict[str, Any] = Field(default_factory=dict)
    is_running: bool = False
    running_execution_id: int | None = None
    created_at: datetime
    updated_at: datetime


class SyncRunIn(BaseModel):
    strategy: SyncStrategy | None = None


class SyncCancelIn(BaseModel):
    message: str | None = Field(default=None, max_length=2000)

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TaskBase(BaseModel):
    task_type: str = Field(default="generic", max_length=32)
    taskname: str = Field(min_length=1, max_length=255)
    shareurl: str = Field(min_length=1)
    shareurls: list[str] | None = None
    savepath: str = Field(min_length=1, max_length=255)
    sync_task_uids: list[str] | None = None
    pattern: str | None = Field(default=None, max_length=255)
    replace: str | None = Field(default=None, max_length=255)
    enddate: str | None = Field(default=None, max_length=32)
    ignore_extension: bool = False
    sort_index: int | None = None
    startfid: str | None = Field(
        default=None,
        max_length=128,
        description="起始集数锚点（如 S01E92 / E92）。按重命名后剧集号过滤，转存 >= 该集；兼容旧版网盘文件 FID。",
    )
    account_name: str | None = Field(default=None, max_length=128)
    update_subdir: str | None = Field(default=None, max_length=255)
    tmdb_id: int | None = None
    tmdb_media_type: str | None = Field(default=None, max_length=8)
    enabled: bool = True
    addition: dict[str, Any] = {}
    extra: dict[str, Any] = {}


class TaskCreateIn(TaskBase):
    task_uid: str | None = Field(default=None, max_length=64)


class TaskUpdateIn(BaseModel):
    task_type: str | None = Field(default=None, max_length=32)
    taskname: str | None = Field(default=None, min_length=1, max_length=255)
    shareurl: str | None = None
    shareurls: list[str] | None = None
    savepath: str | None = Field(default=None, min_length=1, max_length=255)
    sync_task_uids: list[str] | None = None
    pattern: str | None = Field(default=None, max_length=255)
    replace: str | None = Field(default=None, max_length=255)
    enddate: str | None = Field(default=None, max_length=32)
    ignore_extension: bool | None = None
    sort_index: int | None = None
    startfid: str | None = Field(
        default=None,
        max_length=128,
        description="起始集数锚点（如 S01E92 / E92）。按重命名后剧集号过滤，转存 >= 该集；兼容旧版网盘文件 FID。",
    )
    account_name: str | None = Field(default=None, max_length=128)
    update_subdir: str | None = Field(default=None, max_length=255)
    tmdb_id: int | None = None
    tmdb_media_type: str | None = Field(default=None, max_length=8)
    enabled: bool | None = None
    addition: dict[str, Any] | None = None
    extra: dict[str, Any] | None = None


class TaskStatusIn(BaseModel):
    enabled: bool


class TaskShareUrlOut(BaseModel):
    url: str
    status: str = "unknown"
    reason: str | None = None
    last_checked_at: str | None = None
    added_at: str | None = None
    source: str | None = None
    is_active: bool = False


class TaskShareUrlsCheckItemOut(BaseModel):
    url: str
    ok: bool
    message: str | None = None
    status: str = "unknown"
    latest_video: dict[str, Any] | None = None


class TaskShareUrlsCheckOut(BaseModel):
    items: list[TaskShareUrlsCheckItemOut] = []


class TaskShareUrlsCheckIn(BaseModel):
    shareurls: list[str] | None = None


class TaskShareUrlActivateIn(BaseModel):
    shareurl: str = Field(min_length=1)


class TaskExecutionOut(BaseModel):
    id: int
    task_id: int
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    tree_summary: str | None = None
    message: str | None = None
    stage: str | None = None
    run_log: str | None = None
    adapter_snapshot: dict[str, Any] = {}
    plugins_snapshot: list[dict[str, Any]] = []


class DramaUpdateProgressOut(BaseModel):
    available: bool = False
    tmdb_season: int | None = None
    tmdb_episode: int | None = None
    saved_season: int | None = None
    saved_episode: int | None = None
    behind_episodes: int | None = None
    is_latest: bool | None = None
    snapshot_captured_at: datetime | None = None
    reason: str | None = None


class TaskOut(BaseModel):
    id: int
    task_uid: str
    task_type: str
    taskname: str
    shareurl: str
    savepath: str
    sync_task_uids: list[str] = []
    pattern: str | None = None
    replace: str | None = None
    enddate: str | None = None
    ignore_extension: bool
    sort_index: int | None = None
    startfid: str | None = None
    account_name: str | None = None
    update_subdir: str | None = None
    shareurl_ban: str | None = None
    shareurls: list[TaskShareUrlOut] = []
    tmdb_id: int | None = None
    tmdb_media_type: str | None = None
    tmdb_status: str | None = None
    tmdb_is_ended: bool | None = None
    drama_update_progress: DramaUpdateProgressOut | None = None
    # TMDB 推断的更新日（ISO：周一=1 … 周日=7），用于前端判断「今日是否会触发」
    tmdb_episode_weekdays: list[int] = []
    tmdb_update_weekdays: list[int] = []
    # 按与调度相同的规则：今日是否会真正跑追剧任务
    would_run_today: bool = False
    enabled: bool
    addition: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    executions: list[TaskExecutionOut] = []
    created_at: datetime
    updated_at: datetime


class StopCompletedDramaTasksOut(BaseModel):
    checked: int = 0
    matched: int = 0
    stopped: int = 0
    task_ids: list[int] = []


class SavepathSnapshotSyncItemOut(BaseModel):
    task_id: int
    task_uid: str
    taskname: str
    ok: bool
    message: str | None = None


class SavepathSnapshotSyncOut(BaseModel):
    checked: int = 0
    synced: int = 0
    skipped: int = 0
    failed: int = 0
    items: list[SavepathSnapshotSyncItemOut] = []

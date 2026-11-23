from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task_scheduler_setting import TaskSchedulerSetting
from app.services.scheduler_validation import validate_scheduler_setting


DEFAULT_TASK_SCHEDULER_SETTING_ID = 1


def get_or_create_task_scheduler_setting(db: Session) -> TaskSchedulerSetting:
    setting = (
        db.execute(select(TaskSchedulerSetting).where(TaskSchedulerSetting.id == DEFAULT_TASK_SCHEDULER_SETTING_ID))
        .scalars()
        .first()
    )
    if setting is not None:
        return setting
    setting = TaskSchedulerSetting(id=DEFAULT_TASK_SCHEDULER_SETTING_ID)
    db.add(setting)
    db.flush()
    return setting


def update_task_scheduler_setting(
    db: Session,
    *,
    enabled: bool | None = None,
    crontab: str | None = None,
    timezone: str | None = None,
    openlist_cleanup_enabled: bool | None = None,
    openlist_cleanup_path: str | None = None,
    openlist_cleanup_crontab: str | None = None,
) -> TaskSchedulerSetting:
    setting = get_or_create_task_scheduler_setting(db)
    next_crontab = crontab if crontab is not None else getattr(setting, "crontab", None)
    next_timezone = timezone if timezone is not None else getattr(setting, "timezone", None)
    normalized_crontab, normalized_timezone = validate_scheduler_setting(next_crontab, next_timezone)
    if enabled is not None:
        setting.enabled = enabled
    setting.crontab = normalized_crontab
    setting.timezone = normalized_timezone

    if openlist_cleanup_enabled is not None:
        setting.openlist_cleanup_enabled = bool(openlist_cleanup_enabled)
    if openlist_cleanup_path is not None:
        setting.openlist_cleanup_path = str(openlist_cleanup_path or "").strip()

    next_cleanup_crontab = (
        openlist_cleanup_crontab
        if openlist_cleanup_crontab is not None
        else getattr(setting, "openlist_cleanup_crontab", None)
    )
    # 清理调度未启用时允许空 crontab；启用时与主调度共用校验
    if bool(getattr(setting, "openlist_cleanup_enabled", False)) or (
        openlist_cleanup_crontab is not None and str(openlist_cleanup_crontab or "").strip()
    ):
        cleanup_cron, _ = validate_scheduler_setting(next_cleanup_crontab or "0 3 * * *", normalized_timezone)
        setting.openlist_cleanup_crontab = cleanup_cron
    elif openlist_cleanup_crontab is not None:
        setting.openlist_cleanup_crontab = str(openlist_cleanup_crontab or "").strip() or "0 3 * * *"

    db.flush()
    return setting

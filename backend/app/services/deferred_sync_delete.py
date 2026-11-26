"""同步完成后的延时删除：与同步任务联动，落盘后由独立调度触发真正删除。

根因：到期后若再走 SyncExecutor._apply_actions 且 delay>0，会反复重新调度、从不真删。
到期执行时必须 force_immediate_delete=True（或 delay=0），直接走删除分支。
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from app.core.settings import settings

logger = logging.getLogger(__name__)

_TZ = ZoneInfo("Asia/Shanghai")
_lock = threading.Lock()
_run_lock = threading.Lock()


def _store_dir() -> Path:
    path = Path(settings.resolved_app_data_dir) / "deferred_sync_deletes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(job_id: str) -> Path:
    safe = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in ("-", "_"))
    return _store_dir() / f"{safe}.json"


def _now() -> datetime:
    return datetime.now(_TZ)


def _parse_iso(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_TZ)
        return dt.astimezone(_TZ)
    except Exception:
        return None


def serialize_delete_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保留 Endpoint 的 base path + dst_rel，禁止预先拼成绝对路径（否则 _delete_at 会二次拼接）。"""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for a in actions:
        if a.get("kind") != "delete":
            continue
        dst = a.get("dst")
        dst_type = getattr(dst, "type", None) or (dst.get("type") if isinstance(dst, dict) else None)
        dst_path = getattr(dst, "path", None) or (dst.get("path") if isinstance(dst, dict) else None)
        dst_rel = str(a.get("dst_rel") or "").replace("\\", "/").strip().lstrip("/")
        if not dst_type or dst_path is None:
            continue
        dtype = str(dst_type).strip().lower()
        base = str(dst_path).replace("\\", "/").strip()
        key = f"{dtype}:{base}:{dst_rel}"
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "kind": "delete",
                "dst": {"type": dtype, "path": base},
                "dst_rel": dst_rel,
            }
        )
    return out


def schedule_deferred_sync_deletes(
    *,
    sync_task_id: int,
    execution_id: int,
    delay_minutes: int,
    actions: list[dict[str, Any]],
    strategy: dict[str, Any],
) -> dict[str, Any] | None:
    payload_actions = serialize_delete_actions(actions)
    if not payload_actions:
        logger.warning(
            "deferred sync delete skipped: no serializable delete actions execution_id=%s",
            execution_id,
        )
        return None
    delay = max(1, int(delay_minutes or 0))
    run_at = _now() + timedelta(minutes=delay)
    job_id = f"sync_delete_{int(execution_id)}"
    job = {
        "id": job_id,
        "sync_task_id": int(sync_task_id or 0),
        "execution_id": int(execution_id),
        "delay_minutes": delay,
        "run_at": run_at.isoformat(),
        "created_at": _now().isoformat(),
        "status": "pending",
        "actions": payload_actions,
        "strategy": dict(strategy or {}),
    }
    path = _job_path(job_id)
    with _lock:
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from apscheduler.triggers.date import DateTrigger

        from app.extensions.runtime.task_scheduler import task_scheduler_manager

        scheduler = getattr(task_scheduler_manager, "scheduler", None)
        if scheduler is not None:
            scheduler.add_job(
                process_due_deferred_sync_deletes,
                trigger=DateTrigger(run_date=run_at, timezone=_TZ),
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(120, delay * 60),
            )
    except Exception as exc:
        logger.warning("schedule deferred sync delete job failed job_id=%s err=%s", job_id, exc)

    logger.info(
        "scheduled deferred sync delete job_id=%s sync_task_id=%s execution_id=%s delay_min=%s actions=%s run_at=%s",
        job_id,
        sync_task_id,
        execution_id,
        delay,
        len(payload_actions),
        run_at.isoformat(),
    )
    return job


def list_pending_jobs() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    with _lock:
        for path in sorted(_store_dir().glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(raw, dict) and str(raw.get("status") or "") == "pending":
                items.append(raw)
    return items


def _claim_job(job_id: str) -> dict[str, Any] | None:
    """原子地把 pending 置为 running，避免 DateTrigger 与轮询重复执行。"""
    path = _job_path(job_id)
    with _lock:
        if not path.exists():
            return None
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(job, dict) or str(job.get("status") or "") != "pending":
            return None
        job["status"] = "running"
        job["started_at"] = _now().isoformat()
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return job


def _mark_job(job_id: str, *, status: str, message: str | None = None, extra: dict[str, Any] | None = None) -> None:
    path = _job_path(job_id)
    with _lock:
        if not path.exists():
            return
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(job, dict):
            return
        job["status"] = status
        job["finished_at"] = _now().isoformat()
        if message:
            job["message"] = message
        if extra:
            job.update(extra)
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_execution_log(execution_id: int, lines: list[str], *, deleted: int = 0, failed: int = 0) -> None:
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.sync_execution import SyncExecution

    text = "\n".join(lines).rstrip() + "\n"
    with SessionLocal() as db:
        row = db.execute(select(SyncExecution).where(SyncExecution.id == int(execution_id))).scalar_one_or_none()
        if row is None:
            return
        prev = str(getattr(row, "run_log", "") or "")
        row.run_log = (prev.rstrip() + "\n\n" + text).strip() + "\n"
        row.heartbeat_at = datetime.now()
        try:
            stats = json.loads(str(row.stats_json or "") or "{}")
        except Exception:
            stats = {}
        if not isinstance(stats, dict):
            stats = {}
        stats["deferred_delete_status"] = "done" if failed == 0 else "partial"
        stats["deferred_delete_finished_at"] = _now().isoformat()
        stats["deferred_delete_deleted"] = int(deleted)
        stats["deferred_delete_failed"] = int(failed)
        row.stats_json = json.dumps(stats, ensure_ascii=False)
        db.add(row)
        db.commit()


def _run_job(job: dict[str, Any]) -> None:
    from app.extensions.runtime.execution_log import ExecutionLog
    from app.extensions.runtime.sync_executor import Endpoint, Strategy, SyncExecutor

    job_id = str(job.get("id") or "")
    execution_id = int(job.get("execution_id") or 0)
    actions_raw = job.get("actions") if isinstance(job.get("actions"), list) else []
    strategy_raw = job.get("strategy") if isinstance(job.get("strategy"), dict) else {}

    actions: list[dict[str, Any]] = []
    for item in actions_raw:
        if not isinstance(item, dict):
            continue
        dst = item.get("dst") if isinstance(item.get("dst"), dict) else {}
        dst_type = str(dst.get("type") or "").strip().lower()
        dst_path = str(dst.get("path") or "").strip()
        dst_rel = str(item.get("dst_rel") or "").replace("\\", "/").strip().lstrip("/")
        if not dst_type or not dst_path:
            continue
        actions.append(
            {
                "kind": "delete",
                "dst": Endpoint(type=dst_type, path=dst_path),  # type: ignore[arg-type]
                "dst_rel": dst_rel,
            }
        )
    if not actions:
        _mark_job(job_id, status="skipped", message="no_actions")
        return

    # 到期执行：必须 delay=0，并用 force_immediate_delete 阻断再次调度
    strategy = Strategy(
        overwrite=bool(strategy_raw.get("overwrite", False)),
        one_way_delete_extras=True,
        one_way_delete_extras_delay_minutes=0,
        force_refresh=bool(strategy_raw.get("force_refresh", False)),
        concurrency=int(strategy_raw.get("concurrency") or 4),
        request_interval_seconds=float(strategy_raw.get("request_interval_seconds") or 0.0),
        openlist_copy_batch_size=int(strategy_raw.get("openlist_copy_batch_size") or 200),
        unzip_zip_after_sync=bool(strategy_raw.get("unzip_zip_after_sync", True)),
    )

    log = ExecutionLog()
    log.set_stage("deferred_delete")
    log.section("延时删除（同步任务联动）")
    log.line(f"execution_id={execution_id} actions={len(actions)}")

    stats: dict[str, Any] = {
        "total_files": len(actions),
        "done_files": 0,
        "copied_files": 0,
        "deleted_files": 0,
        "skipped_files": 0,
        "failed_files": 0,
        "recent_events": [],
    }

    def on_persist(_force: bool) -> None:
        return

    def on_event(_evt: dict[str, Any] | None) -> None:
        return

    def display_path(endpoint: Endpoint, rel: str) -> str:
        return f"{endpoint.type}:{endpoint.path.rstrip('/')}/{str(rel).lstrip('/')}"

    def on_file_update(*_args: Any, **_kwargs: Any) -> None:
        return

    executor = SyncExecutor(db=None)
    try:
        executor._apply_actions(
            actions,
            strategy=strategy,
            log=log,
            sync_execution_id=0,
            stats=stats,
            max_events=50,
            on_event=on_event,
            on_persist=on_persist,
            display_path=display_path,
            on_file_update=on_file_update,
            cancel_checker=None,
            force_immediate_delete=True,
        )
        deleted = int(stats.get("deleted_files") or 0)
        failed = int(stats.get("failed_files") or 0)
        skipped = int(stats.get("skipped_files") or 0)
        status = "done" if failed == 0 else "failed"
        _mark_job(
            job_id,
            status=status,
            message=None if failed == 0 else f"failed={failed}",
            extra={"deleted": deleted, "failed": failed, "skipped": skipped},
        )
        _append_execution_log(
            execution_id,
            [
                "## 延时删除（同步任务联动）",
                f"完成: deleted={deleted} skipped={skipped} failed={failed}",
                log.render(),
            ],
            deleted=deleted,
            failed=failed,
        )
        logger.info(
            "deferred sync delete finished job_id=%s deleted=%s skipped=%s failed=%s",
            job_id,
            deleted,
            skipped,
            failed,
        )
    except Exception as exc:
        message = str(exc).strip() or type(exc).__name__
        logger.exception("deferred sync delete failed job_id=%s", job_id)
        _mark_job(job_id, status="failed", message=message)
        try:
            _append_execution_log(execution_id, ["## 延时删除（同步任务联动）", f"失败: {message}"], failed=1)
        except Exception:
            pass


def process_due_deferred_sync_deletes() -> int:
    """处理到期的延时删除任务；由 DateTrigger 或周期轮询调用（与 OpenList 清理无关）。"""
    if not _run_lock.acquire(blocking=False):
        return 0
    try:
        now = _now()
        due_ids: list[str] = []
        for job in list_pending_jobs():
            run_at = _parse_iso(str(job.get("run_at") or ""))
            if run_at is None or run_at <= now:
                due_ids.append(str(job.get("id") or ""))
        done = 0
        for job_id in due_ids:
            if not job_id:
                continue
            claimed = _claim_job(job_id)
            if claimed is None:
                continue
            try:
                _run_job(claimed)
                done += 1
            except Exception as exc:
                logger.exception("process deferred sync delete failed job_id=%s err=%s", job_id, exc)
                _mark_job(job_id, status="failed", message=str(exc))
        if due_ids:
            logger.info("deferred sync delete processed due=%s done=%s", len(due_ids), done)
        return done
    finally:
        _run_lock.release()

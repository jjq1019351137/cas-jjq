"""同步完成后的延时删除：与主同步进程分离，落盘后由调度器触发。"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.core.settings import settings

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _store_dir() -> Path:
    path = Path(settings.resolved_app_data_dir) / "deferred_sync_deletes"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _job_path(job_id: str) -> Path:
    safe = "".join(ch for ch in str(job_id) if ch.isalnum() or ch in ("-", "_"))
    return _store_dir() / f"{safe}.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def serialize_delete_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in actions:
        if a.get("kind") != "delete":
            continue
        dst = a.get("dst")
        dst_type = getattr(dst, "type", None) or (dst.get("type") if isinstance(dst, dict) else None)
        dst_path = getattr(dst, "path", None) or (dst.get("path") if isinstance(dst, dict) else None)
        if not dst_type or not dst_path:
            continue
        out.append(
            {
                "kind": "delete",
                "dst": {"type": str(dst_type), "path": str(dst_path)},
                "dst_rel": str(a.get("dst_rel") or ""),
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
        return None
    delay = max(1, int(delay_minutes or 0))
    run_at = _utcnow() + timedelta(minutes=delay)
    job_id = f"sync_delete_{int(execution_id)}"
    job = {
        "id": job_id,
        "sync_task_id": int(sync_task_id),
        "execution_id": int(execution_id),
        "delay_minutes": delay,
        "run_at": run_at.isoformat(),
        "created_at": _utcnow().isoformat(),
        "status": "pending",
        "actions": payload_actions,
        "strategy": dict(strategy or {}),
    }
    path = _job_path(job_id)
    with _lock:
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        from app.extensions.runtime.task_scheduler import task_scheduler_manager

        scheduler = getattr(task_scheduler_manager, "scheduler", None)
        if scheduler is not None:
            scheduler.add_job(
                process_due_deferred_sync_deletes,
                trigger="date",
                run_date=run_at,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(60, delay * 60),
            )
    except Exception as exc:
        logger.warning("schedule deferred sync delete job failed job_id=%s err=%s", job_id, exc)

    logger.info(
        "scheduled deferred sync delete job_id=%s execution_id=%s delay_min=%s actions=%s",
        job_id,
        execution_id,
        delay,
        len(payload_actions),
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


def _mark_job(job_id: str, *, status: str, message: str | None = None) -> None:
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
        job["finished_at"] = _utcnow().isoformat()
        if message:
            job["message"] = message
        path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_execution_log(execution_id: int, lines: list[str]) -> None:
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
        stats["deferred_delete_status"] = "done"
        stats["deferred_delete_finished_at"] = _utcnow().isoformat()
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
        dst_type = str(dst.get("type") or "").strip()
        dst_path = str(dst.get("path") or "").strip()
        if not dst_type or not dst_path:
            continue
        actions.append(
            {
                "kind": "delete",
                "dst": Endpoint(type=dst_type, path=dst_path),  # type: ignore[arg-type]
                "dst_rel": str(item.get("dst_rel") or ""),
            }
        )
    if not actions:
        _mark_job(job_id, status="skipped", message="no_actions")
        return

    delay_default = int(strategy_raw.get("one_way_delete_extras_delay_minutes") or 5)
    strategy = Strategy(
        overwrite=bool(strategy_raw.get("overwrite", False)),
        one_way_delete_extras=True,
        one_way_delete_extras_delay_minutes=delay_default,
        force_refresh=bool(strategy_raw.get("force_refresh", False)),
        concurrency=int(strategy_raw.get("concurrency") or 4),
        request_interval_seconds=float(strategy_raw.get("request_interval_seconds") or 0.0),
        openlist_copy_batch_size=int(strategy_raw.get("openlist_copy_batch_size") or 200),
        unzip_zip_after_sync=bool(strategy_raw.get("unzip_zip_after_sync", True)),
    )

    log = ExecutionLog()
    log.set_stage("deferred_delete")
    log.section("延时删除（独立任务）")
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
        )
        _mark_job(job_id, status="done")
        _append_execution_log(
            execution_id,
            [
                "## 延时删除（独立任务）",
                f"完成: deleted={int(stats.get('deleted_files') or 0)} failed={int(stats.get('failed_files') or 0)}",
                log.render(),
            ],
        )
    except Exception as exc:
        message = str(exc).strip() or type(exc).__name__
        logger.exception("deferred sync delete failed job_id=%s", job_id)
        _mark_job(job_id, status="failed", message=message)
        try:
            _append_execution_log(execution_id, ["## 延时删除（独立任务）", f"失败: {message}"])
        except Exception:
            pass


def process_due_deferred_sync_deletes() -> int:
    """处理到期的延时删除任务；可由 DateTrigger 或周期轮询调用。"""
    now = _utcnow()
    due: list[dict[str, Any]] = []
    for job in list_pending_jobs():
        run_at = _parse_iso(str(job.get("run_at") or ""))
        if run_at is None or run_at <= now:
            due.append(job)
    done = 0
    for job in due:
        job_id = str(job.get("id") or "")
        try:
            _run_job(job)
            done += 1
        except Exception as exc:
            logger.exception("process deferred sync delete failed job_id=%s err=%s", job_id, exc)
            _mark_job(job_id, status="failed", message=str(exc))
    return done

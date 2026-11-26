"""追剧任务 / 同步任务 JSON 导出与导入（跨容器迁移，不依赖复制 app.db）。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.models.drive_account import DriveAccount
from app.models.sync_task import SyncTask
from app.models.sync_task_drama_link import SyncTaskDramaLink
from app.models.task import Task
from app.services.sync_tasks import create_sync_task, list_sync_tasks, update_sync_task
from app.services.task_share_links import load_share_links
from app.services.tasks import create_task, list_tasks, update_task

FORMAT_DRAMA = "cas-jjq-drama-tasks"
FORMAT_SYNC = "cas-jjq-sync-tasks"
FORMAT_BUNDLE = "cas-jjq-task-bundle"
VERSION = 1


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _drama_links_map(db: Session, task_uids: list[str]) -> dict[str, list[str]]:
    if not task_uids:
        return {}
    rows = db.execute(
        select(SyncTaskDramaLink.task_uid, SyncTaskDramaLink.sync_task_uid)
        .where(SyncTaskDramaLink.task_uid.in_(task_uids))
        .order_by(SyncTaskDramaLink.sort_order.asc())
    ).all()
    out: dict[str, list[str]] = {uid: [] for uid in task_uids}
    for task_uid, sync_uid in rows:
        t = str(task_uid or "").strip()
        s = str(sync_uid or "").strip()
        if t and s:
            out.setdefault(t, []).append(s)
    return out


def _sync_drama_map(db: Session, sync_uids: list[str]) -> dict[str, list[str]]:
    if not sync_uids:
        return {}
    rows = db.execute(
        select(SyncTaskDramaLink.sync_task_uid, SyncTaskDramaLink.task_uid).where(
            SyncTaskDramaLink.sync_task_uid.in_(sync_uids)
        )
    ).all()
    out: dict[str, list[str]] = {uid: [] for uid in sync_uids}
    for sync_uid, task_uid in rows:
        s = str(sync_uid or "").strip()
        t = str(task_uid or "").strip()
        if s and t:
            out.setdefault(s, []).append(t)
    return out


def _account_lookup(db: Session) -> dict[int, DriveAccount]:
    rows = db.execute(select(DriveAccount)).scalars().all()
    return {int(a.id): a for a in rows}


def _resolve_account_id(
    db: Session,
    *,
    account_id: Any,
    account_name: Any,
    drive_type: Any,
    cache: dict[str, int | None] | None = None,
) -> int | None:
    name = str(account_name or "").strip()
    dtype = str(drive_type or "").strip().lower()
    cache_key = f"{dtype}|{name}|{account_id}"
    if cache is not None and cache_key in cache:
        return cache[cache_key]

    resolved: int | None = None
    if name:
        q = select(DriveAccount).where(DriveAccount.name == name)
        if dtype:
            q = q.where(DriveAccount.drive_type == dtype)
        row = db.execute(q.order_by(DriveAccount.id.asc())).scalars().first()
        if row is not None:
            resolved = int(row.id)
    if resolved is None and account_id not in (None, "", 0, "0"):
        try:
            aid = int(account_id)
        except Exception:
            aid = 0
        if aid > 0 and db.get(DriveAccount, aid) is not None:
            resolved = aid

    if cache is not None:
        cache[cache_key] = resolved
    return resolved


def export_drama_tasks(db: Session) -> dict[str, Any]:
    tasks = list_tasks(db)
    uids = [str(t.task_uid) for t in tasks]
    sync_map = _drama_links_map(db, uids)
    items: list[dict[str, Any]] = []
    for t in tasks:
        shareurls = [str(x.get("url") or "").strip() for x in load_share_links(t) if str(x.get("url") or "").strip()]
        if not shareurls and t.shareurl:
            shareurls = [str(t.shareurl)]
        items.append(
            {
                "task_uid": str(t.task_uid),
                "task_type": str(t.task_type or "generic"),
                "taskname": str(t.taskname or ""),
                "shareurl": str(t.shareurl or ""),
                "shareurls": shareurls,
                "savepath": str(t.savepath or ""),
                "sync_task_uids": list(sync_map.get(str(t.task_uid), [])),
                "pattern": t.pattern,
                "replace": t.replace,
                "enddate": t.enddate,
                "ignore_extension": bool(t.ignore_extension),
                "sort_index": t.sort_index,
                "startfid": t.startfid,
                "account_name": t.account_name,
                "update_subdir": t.update_subdir,
                "tmdb_id": t.tmdb_id,
                "tmdb_media_type": t.tmdb_media_type,
                "enabled": bool(t.enabled),
                "addition": _loads_json(t.addition_json),
                "extra": _loads_json(t.extra_json),
            }
        )
    return {
        "format": FORMAT_DRAMA,
        "version": VERSION,
        "exported_at": _utcnow_iso(),
        "count": len(items),
        "tasks": items,
    }


def export_sync_tasks(db: Session) -> dict[str, Any]:
    rows = list_sync_tasks(db)
    accounts = _account_lookup(db)
    drama_map = _sync_drama_map(db, [str(t.uid) for t in rows])
    items: list[dict[str, Any]] = []
    for t in rows:
        def _ep(tp: str, path: str, account_id: int | None) -> dict[str, Any]:
            out: dict[str, Any] = {"type": str(tp or ""), "path": str(path or "")}
            if str(tp or "") == "netdisk":
                acc = accounts.get(int(account_id or 0))
                out["account_id"] = int(account_id) if account_id else None
                out["account_name"] = getattr(acc, "name", None) if acc else None
                out["drive_type"] = getattr(acc, "drive_type", None) if acc else None
            return out

        items.append(
            {
                "uid": str(t.uid),
                "name": str(t.name or ""),
                "enabled": bool(t.enabled),
                "source": _ep(t.source_type, t.source_path, getattr(t, "source_account_id", None)),
                "target": _ep(t.target_type, t.target_path, getattr(t, "target_account_id", None)),
                "mode": str(t.mode or "one_way"),
                "strategy": _loads_json(t.strategy_json),
                "drama_task_uids": list(drama_map.get(str(t.uid), [])),
                "addition": _loads_json(getattr(t, "addition_json", None)),
            }
        )
    return {
        "format": FORMAT_SYNC,
        "version": VERSION,
        "exported_at": _utcnow_iso(),
        "count": len(items),
        "tasks": items,
    }


def export_task_bundle(db: Session) -> dict[str, Any]:
    drama = export_drama_tasks(db)
    sync = export_sync_tasks(db)
    return {
        "format": FORMAT_BUNDLE,
        "version": VERSION,
        "exported_at": _utcnow_iso(),
        "drama_tasks": drama.get("tasks") or [],
        "sync_tasks": sync.get("tasks") or [],
        "count": {
            "drama_tasks": len(drama.get("tasks") or []),
            "sync_tasks": len(sync.get("tasks") or []),
        },
    }


def _extract_task_list(payload: dict[str, Any], *, prefer: str) -> list[dict[str, Any]]:
    fmt = str(payload.get("format") or "").strip()
    if prefer == "drama":
        if fmt == FORMAT_BUNDLE:
            raw = payload.get("drama_tasks")
        else:
            raw = payload.get("tasks")
    else:
        if fmt == FORMAT_BUNDLE:
            raw = payload.get("sync_tasks")
        else:
            raw = payload.get("tasks")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]


def import_drama_tasks(
    db: Session,
    payload: dict[str, Any],
    *,
    mode: str = "skip",
) -> dict[str, Any]:
    """mode: skip=同 task_uid 跳过; upsert=同 uid 更新。"""
    mode = str(mode or "skip").strip().lower()
    if mode not in {"skip", "upsert"}:
        raise bad_request("TASK_IMPORT_MODE_INVALID", "导入模式无效，仅支持 skip/upsert")
    fmt = str(payload.get("format") or "").strip()
    if fmt and fmt not in {FORMAT_DRAMA, FORMAT_BUNDLE}:
        raise bad_request("TASK_IMPORT_FORMAT_INVALID", "追剧任务导入格式无效")
    items = _extract_task_list(payload, prefer="drama")
    if not items:
        raise bad_request("TASK_IMPORT_EMPTY", "没有可导入的追剧任务")

    existing_rows = list(db.execute(select(Task)).scalars().all())
    existing = {str(t.task_uid): t for t in existing_rows}
    # 无 uid 时的内容指纹去重：taskname + shareurl + savepath
    existing_fingerprints: dict[str, Task] = {}
    for t in existing_rows:
        fp = f"{str(t.taskname or '').strip()}|{str(t.shareurl or '').strip()}|{str(t.savepath or '').strip()}"
        if fp != "||":
            existing_fingerprints.setdefault(fp, t)
    existing_sync_uids = {
        str(u)
        for u in db.execute(select(SyncTask.uid)).scalars().all()
        if str(u or "").strip()
    }
    created = 0
    updated = 0
    skipped = 0
    failed: list[dict[str, str]] = []
    seen_uids: set[str] = set()
    seen_fps: set[str] = set()

    for item in items:
        name = str(item.get("taskname") or "").strip() or "(未命名)"
        try:
            uid = str(item.get("task_uid") or "").strip()
            shareurls = item.get("shareurls")
            if not isinstance(shareurls, list):
                shareurls = None
            raw_sync_uids = item.get("sync_task_uids") if isinstance(item.get("sync_task_uids"), list) else []
            sync_task_uids = [str(x).strip() for x in raw_sync_uids if str(x).strip() in existing_sync_uids]
            body = {
                "task_uid": uid or None,
                "task_type": str(item.get("task_type") or "drama"),
                "taskname": str(item.get("taskname") or "").strip(),
                "shareurl": str(item.get("shareurl") or "").strip(),
                "shareurls": shareurls,
                "savepath": str(item.get("savepath") or "").strip(),
                "sync_task_uids": sync_task_uids,
                "pattern": item.get("pattern"),
                "replace": item.get("replace"),
                "enddate": item.get("enddate"),
                "ignore_extension": bool(item.get("ignore_extension", False)),
                "sort_index": item.get("sort_index"),
                "startfid": item.get("startfid"),
                "account_name": item.get("account_name"),
                "update_subdir": item.get("update_subdir"),
                "tmdb_id": item.get("tmdb_id"),
                "tmdb_media_type": item.get("tmdb_media_type"),
                "enabled": bool(item.get("enabled", True)),
                "addition": item.get("addition") if isinstance(item.get("addition"), dict) else {},
                "extra": item.get("extra") if isinstance(item.get("extra"), dict) else {},
            }
            if not body["taskname"] or not body["shareurl"] or not body["savepath"]:
                raise bad_request("TASK_IMPORT_ITEM_INVALID", "任务缺少名称/分享链接/保存路径")

            fp = f"{body['taskname']}|{body['shareurl']}|{body['savepath']}"
            # 同一 JSON 内去重
            if uid and uid in seen_uids:
                skipped += 1
                continue
            if fp in seen_fps:
                skipped += 1
                continue

            hit = existing.get(uid) if uid else None
            if hit is None and mode == "skip":
                hit = existing_fingerprints.get(fp)

            if hit is not None:
                if mode == "skip":
                    skipped += 1
                    if uid:
                        seen_uids.add(uid)
                    seen_fps.add(fp)
                    continue
                update_payload = dict(body)
                update_payload.pop("task_uid", None)
                update_task(db, int(hit.id), **update_payload)
                updated += 1
                existing[str(hit.task_uid)] = hit
                existing_fingerprints[fp] = hit
            else:
                row = create_task(db, **body)
                created += 1
                existing[str(row.task_uid)] = row
                existing_fingerprints[fp] = row
            if uid:
                seen_uids.add(uid)
            seen_fps.add(fp)
        except Exception as exc:
            failed.append({"taskname": name, "error": str(getattr(exc, "message", None) or exc)})

    db.flush()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "total": len(items),
    }


def import_sync_tasks(
    db: Session,
    payload: dict[str, Any],
    *,
    mode: str = "skip",
) -> dict[str, Any]:
    mode = str(mode or "skip").strip().lower()
    if mode not in {"skip", "upsert"}:
        raise bad_request("SYNC_IMPORT_MODE_INVALID", "导入模式无效，仅支持 skip/upsert")
    fmt = str(payload.get("format") or "").strip()
    if fmt and fmt not in {FORMAT_SYNC, FORMAT_BUNDLE}:
        raise bad_request("SYNC_IMPORT_FORMAT_INVALID", "同步任务导入格式无效")
    items = _extract_task_list(payload, prefer="sync")
    if not items:
        raise bad_request("SYNC_IMPORT_EMPTY", "没有可导入的同步任务")

    existing_rows = list_sync_tasks(db)
    existing = {str(t.uid): t for t in existing_rows}
    # 无 uid 时的内容指纹：name + source + target
    existing_fingerprints: dict[str, SyncTask] = {}
    for t in existing_rows:
        fp = (
            f"{str(t.name or '').strip()}|"
            f"{str(t.source_type or '').strip()}:{str(t.source_path or '').strip()}|"
            f"{str(t.target_type or '').strip()}:{str(t.target_path or '').strip()}"
        )
        if not fp.startswith("|"):
            existing_fingerprints.setdefault(fp, t)
    existing_drama_uids = {
        str(u)
        for u in db.execute(select(Task.task_uid).where(Task.task_type == "drama")).scalars().all()
        if str(u or "").strip()
    }
    account_cache: dict[str, int | None] = {}
    created = 0
    updated = 0
    skipped = 0
    failed: list[dict[str, str]] = []
    seen_uids: set[str] = set()
    seen_fps: set[str] = set()

    def _normalize_endpoint(raw: Any) -> dict[str, Any]:
        ep = raw if isinstance(raw, dict) else {}
        tp = str(ep.get("type") or "").strip().lower()
        path = str(ep.get("path") or "").strip()
        out: dict[str, Any] = {"type": tp, "path": path}
        if tp == "netdisk":
            aid = _resolve_account_id(
                db,
                account_id=ep.get("account_id"),
                account_name=ep.get("account_name"),
                drive_type=ep.get("drive_type"),
                cache=account_cache,
            )
            if aid is None:
                raise bad_request(
                    "SYNC_IMPORT_ACCOUNT_MISSING",
                    f"无法匹配网盘账号: {ep.get('account_name') or ep.get('account_id') or ''}",
                )
            out["account_id"] = aid
        return out

    for item in items:
        name = str(item.get("name") or "").strip() or "(未命名同步)"
        try:
            uid = str(item.get("uid") or "").strip()
            source = _normalize_endpoint(item.get("source"))
            target = _normalize_endpoint(item.get("target"))
            body = {
                "name": str(item.get("name") or "").strip(),
                "enabled": bool(item.get("enabled", True)),
                "source": source,
                "target": target,
                "mode": str(item.get("mode") or "one_way"),
                "strategy": item.get("strategy") if isinstance(item.get("strategy"), dict) else {},
                "drama_task_uids": [
                    str(x).strip()
                    for x in (item.get("drama_task_uids") if isinstance(item.get("drama_task_uids"), list) else [])
                    if str(x).strip() in existing_drama_uids
                ],
                "addition": item.get("addition") if isinstance(item.get("addition"), dict) else {},
            }
            if not body["name"]:
                raise bad_request("SYNC_IMPORT_ITEM_INVALID", "同步任务缺少名称")

            fp = (
                f"{body['name']}|"
                f"{source.get('type')}:{source.get('path')}|"
                f"{target.get('type')}:{target.get('path')}"
            )
            if uid and uid in seen_uids:
                skipped += 1
                continue
            if fp in seen_fps:
                skipped += 1
                continue

            hit = existing.get(uid) if uid else None
            if hit is None and mode == "skip":
                hit = existing_fingerprints.get(fp)

            if hit is not None:
                if mode == "skip":
                    skipped += 1
                    if uid:
                        seen_uids.add(uid)
                    seen_fps.add(fp)
                    continue
                update_sync_task(db, int(hit.id), **body)
                updated += 1
                existing[str(hit.uid)] = hit
                existing_fingerprints[fp] = hit
            else:
                task = create_sync_task(db, **body)
                # 尽量保留原 uid，便于与追剧任务关联
                if uid and str(task.uid) != uid:
                    clash = db.execute(select(SyncTask).where(SyncTask.uid == uid)).scalars().first()
                    if clash is None:
                        task.uid = uid
                        db.flush()
                created += 1
                existing[str(task.uid)] = task
                existing_fingerprints[fp] = task
            if uid:
                seen_uids.add(uid)
            seen_fps.add(fp)
        except Exception as exc:
            failed.append({"name": name, "error": str(getattr(exc, "message", None) or exc)})

    db.flush()
    return {
        "ok": True,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "total": len(items),
    }

"""OpenList 网盘目录定时清理：递归删除指定目录下的 .mp4 / .zip / .mkv 文件。"""
from __future__ import annotations

import logging
import posixpath
from collections import deque
from typing import Any

from sqlalchemy.orm import Session

from app.services.openlist_client_factory import get_openlist_client

logger = logging.getLogger(__name__)

CLEANUP_EXTS = {".mp4", ".zip", ".mkv"}
_MAX_DIRS = 5000
_MAX_PAGES_PER_DIR = 100


def _norm_openlist_path(path: str) -> str:
    text = str(path or "").strip().replace("\\", "/")
    if not text:
        return ""
    if not text.startswith("/"):
        text = "/" + text
    return posixpath.normpath(text) or "/"


def _list_dir_entries(client: Any, dir_path: str) -> tuple[list[dict[str, Any]], str | None]:
    """分页列出目录条目，返回 (entries, error)。"""
    content: list[dict[str, Any]] = []
    page = 1
    per_page = 200
    while page <= _MAX_PAGES_PER_DIR:
        try:
            resp = client.fs_list(dir_path, refresh=(page == 1), page=page, per_page=per_page)
        except Exception as e:
            return content, f"列目录失败 {dir_path}: {e}"
        data = resp.get("data") if isinstance(resp, dict) else None
        chunk: list[Any] = []
        if isinstance(data, dict):
            chunk = data.get("content") or data.get("items") or data.get("list") or data.get("files") or []
        if not isinstance(chunk, list):
            chunk = []
        for item in chunk:
            if isinstance(item, dict):
                content.append(item)
        if len(chunk) < per_page:
            break
        page += 1
    return content, None


def cleanup_openlist_media_files(db: Session, *, dir_path: str) -> dict[str, Any]:
    """递归遍历 OpenList 目录，删除所有后缀为 .mp4/.zip/.mkv 的文件。"""
    target = _norm_openlist_path(dir_path)
    result: dict[str, Any] = {
        "path": target,
        "dirs_scanned": 0,
        "listed": 0,
        "matched": 0,
        "deleted": 0,
        "failed": 0,
        "names": [],
        "errors": [],
    }
    if not target:
        result["errors"].append("未配置清理路径")
        return result

    try:
        client = get_openlist_client(db)
    except Exception as e:
        result["errors"].append(f"OpenList 客户端不可用: {e}")
        logger.warning("OpenList 清理跳过: 客户端不可用 path=%s err=%s", target, e)
        return result

    # dir -> names to delete in that dir
    deletes_by_dir: dict[str, list[str]] = {}
    queue: deque[str] = deque([target])
    seen_dirs: set[str] = {target}

    while queue:
        current = queue.popleft()
        result["dirs_scanned"] += 1
        entries, err = _list_dir_entries(client, current)
        if err:
            result["errors"].append(err)
            logger.warning("OpenList 清理列目录失败 path=%s err=%s", current, err)
            continue

        for item in entries:
            result["listed"] += 1
            name = str(item.get("name") or "").strip()
            if not name or name in {".", ".."}:
                continue
            child_path = posixpath.normpath(posixpath.join(current.rstrip("/") or "/", name))
            if not child_path.startswith("/"):
                child_path = "/" + child_path

            if bool(item.get("is_dir")):
                if child_path not in seen_dirs and len(seen_dirs) < _MAX_DIRS:
                    seen_dirs.add(child_path)
                    queue.append(child_path)
                continue

            ext = posixpath.splitext(name)[1].lower()
            if ext not in CLEANUP_EXTS:
                continue
            deletes_by_dir.setdefault(current, []).append(name)

    matched_paths: list[str] = []
    for d, names in deletes_by_dir.items():
        for n in names:
            matched_paths.append(posixpath.normpath(posixpath.join(d.rstrip("/") or "/", n)))
    result["matched"] = len(matched_paths)
    result["names"] = matched_paths[:200]

    if not matched_paths:
        logger.info("OpenList 清理: path=%s 递归扫描 dirs=%s 无需删除", target, result["dirs_scanned"])
        return result

    batch_size = 100
    for d, names in deletes_by_dir.items():
        for i in range(0, len(names), batch_size):
            batch = names[i : i + batch_size]
            try:
                client.fs_remove(d, batch)
                result["deleted"] += len(batch)
                logger.info("OpenList 清理删除: dir=%s count=%s names=%s", d, len(batch), batch[:20])
            except Exception as e:
                result["failed"] += len(batch)
                result["errors"].append(f"{d}: {e}")
                logger.warning("OpenList 清理删除失败 dir=%s err=%s batch=%s", d, e, batch[:10])

    logger.info(
        "OpenList 清理完成 path=%s dirs=%s matched=%s deleted=%s failed=%s",
        target,
        result["dirs_scanned"],
        result["matched"],
        result["deleted"],
        result["failed"],
    )
    return result

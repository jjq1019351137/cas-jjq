from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.task import Task

logger = logging.getLogger(__name__)

# 链接列表上限：超限时优先淘汰最旧的 invalid 项
MAX_SHARE_LINKS = 10

STATUS_UNKNOWN = "unknown"
STATUS_OK = "ok"
STATUS_INVALID = "invalid"

_VALID_STATUSES = {STATUS_UNKNOWN, STATUS_OK, STATUS_INVALID}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _normalize_link(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    url = str(item.get("url") or "").strip()
    if not url:
        return None
    status = str(item.get("status") or STATUS_UNKNOWN).strip().lower()
    if status not in _VALID_STATUSES:
        status = STATUS_UNKNOWN
    return {
        "url": url,
        "status": status,
        "reason": str(item.get("reason") or "").strip() or None,
        "last_checked_at": item.get("last_checked_at") or None,
        "added_at": item.get("added_at") or None,
        "source": str(item.get("source") or "manual").strip() or "manual",
    }


def new_link(url: str, *, source: str = "manual", status: str = STATUS_UNKNOWN) -> dict[str, Any]:
    return {
        "url": str(url or "").strip(),
        "status": status if status in _VALID_STATUSES else STATUS_UNKNOWN,
        "reason": None,
        "last_checked_at": None,
        "added_at": _now_iso(),
        "source": source,
    }


def load_share_links(task: Task | Any) -> list[dict[str, Any]]:
    """解析任务的多链接列表；为空/损坏时降级为 [shareurl]；保证活跃链接始终在列表中。"""
    links: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw = getattr(task, "shareurl_list_json", None)
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            data = None
        if isinstance(data, list):
            for item in data:
                link = _normalize_link(item)
                if link is None or link["url"] in seen:
                    continue
                seen.add(link["url"])
                links.append(link)
    active = str(getattr(task, "shareurl", "") or "").strip()
    if active and active not in seen:
        links.insert(0, new_link(active))
    if not links and active:
        links = [new_link(active)]
    return links


def _evict_over_limit(links: list[dict[str, Any]], *, active_url: str) -> list[dict[str, Any]]:
    if len(links) <= MAX_SHARE_LINKS:
        return links
    # 优先淘汰最旧的 invalid 项（按 added_at 升序），活跃链接始终保留
    removable = [
        x for x in links
        if x["url"] != active_url and x["status"] == STATUS_INVALID
    ]
    removable.sort(key=lambda x: str(x.get("added_at") or ""))
    drop_urls: set[str] = set()
    overflow = len(links) - MAX_SHARE_LINKS
    for x in removable[:overflow]:
        drop_urls.add(x["url"])
    links = [x for x in links if x["url"] not in drop_urls]
    # 仍超限时从尾部截断（保留活跃链接）
    while len(links) > MAX_SHARE_LINKS:
        for i in range(len(links) - 1, -1, -1):
            if links[i]["url"] != active_url:
                links.pop(i)
                break
        else:
            break
    return links


def save_share_links(db: Session, task: Task, links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """写回多链接列表：去重、同盘校验、上限淘汰；活跃链接必须在列表中。"""
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in links or []:
        link = _normalize_link(item)
        if link is None or link["url"] in seen:
            continue
        seen.add(link["url"])
        normalized.append(link)
    if not normalized:
        raise bad_request("TASK_SHAREURLS_EMPTY", "分享链接列表不能为空")

    active = str(getattr(task, "shareurl", "") or "").strip()
    if active and active not in seen:
        normalized.insert(0, new_link(active))

    active_url = active or normalized[0]["url"]
    active_drive_type = AdapterRegistry.detect_drive_type(active_url)
    if active_drive_type is None:
        raise bad_request("TASK_SHAREURL_INVALID", "无法识别的网盘分享链接")
    for link in normalized:
        dt = AdapterRegistry.detect_drive_type(link["url"])
        if dt != active_drive_type:
            raise bad_request(
                "TASK_SHAREURLS_DRIVE_TYPE_MISMATCH",
                f"备用链接必须与主链接同网盘类型（{active_drive_type}）",
                detail=link["url"],
            )

    normalized = _evict_over_limit(normalized, active_url=active_url)
    task.shareurl_list_json = json.dumps(normalized, ensure_ascii=False)
    db.flush()
    return normalized


def set_share_links_from_urls(db: Session, task: Task, urls: list[str], *, source: str = "manual") -> list[dict[str, Any]]:
    """按 url 有序列表重建多链接：保留旧元数据，新 url 置 unknown；urls[0] 提升为活跃链接。"""
    cleaned = [str(x or "").strip() for x in (urls or [])]
    cleaned = list(dict.fromkeys(x for x in cleaned if x))
    if not cleaned:
        raise bad_request("TASK_SHAREURLS_EMPTY", "分享链接列表不能为空")
    old_by_url = {x["url"]: x for x in load_share_links(task)}
    links: list[dict[str, Any]] = []
    for url in cleaned:
        old = old_by_url.get(url)
        links.append(old if old is not None else new_link(url, source=source))
    task.shareurl = cleaned[0]
    return save_share_links(db, task, links)


def mark_link_status(db: Session, task_id: int, url: str, *, status: str, reason: str | None = None) -> bool:
    """独立更新单条链接状态 + last_checked_at（不存在则忽略）。"""
    task = db.get(Task, int(task_id))
    if task is None:
        return False
    url = str(url or "").strip()
    links = load_share_links(task)
    changed = False
    for link in links:
        if link["url"] != url:
            continue
        link["status"] = status if status in _VALID_STATUSES else STATUS_UNKNOWN
        link["reason"] = str(reason or "").strip() or None
        link["last_checked_at"] = _now_iso()
        changed = True
        break
    if not changed:
        return False
    task.shareurl_list_json = json.dumps(links, ensure_ascii=False)
    db.flush()
    return True


def promote_link(db: Session, task_id: int, url: str) -> bool:
    """将指定链接提升为活跃链接（移到首位、置 ok、同步 shareurl、清空 shareurl_ban）。"""
    task = db.get(Task, int(task_id))
    if task is None:
        return False
    url = str(url or "").strip()
    links = load_share_links(task)
    hit = next((x for x in links if x["url"] == url), None)
    if hit is None:
        return False
    previous_active = str(getattr(task, "shareurl", "") or "").strip()
    hit["status"] = STATUS_OK
    hit["reason"] = None
    hit["last_checked_at"] = _now_iso()
    links = [hit] + [x for x in links if x["url"] != url]
    task.shareurl = url
    task.shareurl_ban = None
    task.shareurl_list_json = json.dumps(links, ensure_ascii=False)
    if previous_active and previous_active != url:
        # startfid 是旧主链接内的文件 fid，换链后失效，保留会使起始文件过滤静默失效
        task.startfid = None
    db.flush()
    return True


def pick_run_link_candidates(task: Task | Any) -> list[str]:
    """本次运行要处理的全部链接，严格按存储顺序（= 用户设定的转存优先级），跳过已标失效的。

    多链接语义为“多源聚合”：每次运行依次对每条链接做一次转存，哪条先更新就先被转存。
    顺序即优先级：同一集多源都有时，靠前的源先转存，靠后的因去重（目标目录同名比对 +
    转存历史）自动跳过，因此排序决定了最终保留哪个源的版本。
    全部链接都被标失效时回退为仅跑活跃链接，保证任务仍会尝试并能通过失败→封禁→自动修复自愈。
    """
    # load_share_links 已保证活跃链接在列表中（缺失时插入首位），此处不再重排，
    # 以免覆盖用户在界面上调整的优先级
    out = [x["url"] for x in load_share_links(task) if x["status"] != STATUS_INVALID]
    if not out:
        active = str(getattr(task, "shareurl", "") or "").strip()
        return [active] if active else []
    return out


def replace_active_link(
    db: Session,
    task: Task,
    new_url: str,
    *,
    replace_url: str | None = None,
    mark_old_invalid: bool = False,
    old_reason: str | None = None,
    source: str = "repair",
) -> list[dict[str, Any]]:
    """用新链接接管活跃位：新链接插入首位置 ok，旧活跃链接移至尾部（可选标 invalid），清空 shareurl_ban。

    replace_url：被 new_url 替代的原链接（如带 fid 重写前的备用链接），从列表中移除。

    供自动修复/自动换链调用：与新链接不同网盘类型的历史链接会被丢弃（而非抛错），
    避免历史脏数据导致整个任务永远修复失败。
    """
    new_url = str(new_url or "").strip()
    if not new_url:
        raise bad_request("TASK_SHAREURLS_EMPTY", "分享链接列表不能为空")
    new_drive_type = AdapterRegistry.detect_drive_type(new_url)
    old_active = str(getattr(task, "shareurl", "") or "").strip()
    drop = {str(replace_url or "").strip()} - {""}

    def _same_drive(url: str) -> bool:
        return AdapterRegistry.detect_drive_type(url) == new_drive_type

    old_urls = [x["url"] for x in load_share_links(task) if x["url"] not in drop]
    others = [u for u in old_urls if u not in (new_url, old_active) and _same_drive(u)]
    urls = [new_url] + others
    keep_old_active = bool(old_active) and old_active != new_url and _same_drive(old_active)
    if keep_old_active:
        urls.append(old_active)
    links = set_share_links_from_urls(db, task, urls, source=source)
    now = _now_iso()
    if old_active and old_active != new_url:
        # 换链后旧链接内的 startfid 失效，必须清空，否则起始文件过滤会静默失效
        task.startfid = None
    for link in links:
        if link["url"] == new_url:
            link["status"] = STATUS_OK
            link["reason"] = None
            link["last_checked_at"] = now
        elif mark_old_invalid and keep_old_active and link["url"] == old_active:
            link["status"] = STATUS_INVALID
            link["reason"] = str(old_reason or "").strip() or "已被自动修复替换"
            link["last_checked_at"] = now
    task.shareurl_list_json = json.dumps(links, ensure_ascii=False)
    task.shareurl_ban = None
    db.flush()
    return links


def check_task_share_links(db: Session, task: Task, *, shareurls: list[str] | None = None) -> list[dict[str, Any]]:
    """批量验证链接有效性并返回明细（含 latest_video）。

    shareurls 为空时验证任务已保存的全部链接；传入时验证指定列表（供表单内尚未
    保存的备用链接也能拿到结果），但仅为已存在于任务链接列表中的链接写回状态。
    """
    from app.schemas.task_browse import SharePreviewBatchIn
    from app.services.share_preview_batch import preview_share_batch

    links = load_share_links(task)
    stored_by_url = {x["url"]: x for x in links}

    requested = [str(x or "").strip() for x in (shareurls or [])]
    requested = list(dict.fromkeys(x for x in requested if x))
    urls = requested or [x["url"] for x in links]
    if not urls:
        return []

    account_name = str(getattr(task, "account_name", "") or "").strip() or None
    out, _changed = preview_share_batch(db, SharePreviewBatchIn(shareurls=urls, account_name=account_name))
    by_url = {str(getattr(x, "shareurl", "") or "").strip(): x for x in (out.items or [])}
    now = _now_iso()
    results: list[dict[str, Any]] = []
    for url in urls:
        row = by_url.get(url)
        ok = bool(getattr(row, "ok", False)) if row is not None else False
        message = (str(getattr(row, "message", "") or "").strip() or None) if row is not None else "验证无结果"
        status = STATUS_OK if ok else STATUS_INVALID
        link = stored_by_url.get(url)
        if link is not None:
            link["status"] = status
            link["reason"] = None if ok else message
            link["last_checked_at"] = now
        latest = getattr(row, "latest_video", None) if row is not None else None
        results.append(
            {
                "url": url,
                "ok": ok,
                "message": message,
                "status": status,
                "latest_video": latest.model_dump() if latest is not None else None,
            }
        )
    task.shareurl_list_json = json.dumps(links, ensure_ascii=False)
    db.flush()
    return results

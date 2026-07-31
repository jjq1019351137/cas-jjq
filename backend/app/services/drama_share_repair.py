from __future__ import annotations

import logging
import os
import random
import time
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.models.task import Task
from app.schemas.task_browse import SharePreviewBatchIn
from app.services import audit
from app.services.notifications.sender import send_runtime
from app.services.notifications.task_notify import DRAMA_NOTIFY_TITLE
from app.services.invalid_share_links import list_invalid_shareurls
from app.services.drama_share_autoupdate import resolve_drama_shareurl_update
from app.services.resource_search import fetch_task_suggestions
from app.services.share_preview_batch import preview_share_batch
from app.services.title_match import extract_progress, title_matches_names
from app.services.title_vector_match import is_vector_fallback_enabled, vector_recall
from app.services.tmdb_cache import get_tmdb_detail_cached


logger = logging.getLogger(__name__)


def _debug_enabled() -> bool:
    return os.getenv("DEBUG", "0").strip().lower() in {"1", "true", "yes", "y", "on"}


def _clean_keyword(value: str) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    v = v.replace("《", "").replace("》", "")
    v = re.sub(r"[\[\]（）()]+", " ", v).strip()
    v = re.sub(r"[\s\-_\.]+", " ", v).strip()
    v = re.sub(r"(test|测试)\s*$", "", v, flags=re.IGNORECASE).strip()
    v = re.sub(r"\s{2,}", " ", v).strip()
    return v


def _collect_tmdb_names(db: Session, task: Task) -> list[str]:
    tmdb_media_type = str(getattr(task, "tmdb_media_type", "") or "").strip().lower()
    tmdb_id = getattr(task, "tmdb_id", None)
    if tmdb_media_type not in {"tv", "movie"} or tmdb_id is None:
        return []
    try:
        configured, detail, _weekdays, _episode_weekdays, _row = get_tmdb_detail_cached(
            db,
            media_type=tmdb_media_type,  # type: ignore[arg-type]
            tmdb_id=int(tmdb_id),
            force_refresh=False,
        )
    except Exception:
        return []
    if not configured or not isinstance(detail, dict):
        return []
    if tmdb_media_type == "tv":
        raw_names = [detail.get("name"), detail.get("original_name")]
    else:
        raw_names = [detail.get("title"), detail.get("original_title")]
    names: list[str] = []
    for raw in raw_names:
        value = str(raw or "").strip()
        if value and value not in names:
            names.append(value)
    return names


def _pick_match_names(db: Session, task: Task) -> list[str]:
    names = _collect_tmdb_names(db, task)
    if names:
        return names
    fallback = _clean_keyword(str(getattr(task, "taskname", "") or ""))
    return [fallback] if len(fallback) >= 2 else []


def _pick_search_keywords(db: Session, task: Task) -> list[str]:
    keywords: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        v = _clean_keyword(value)
        if len(v) < 2:
            return
        if v in seen:
            return
        seen.add(v)
        keywords.append(v)

    for name in _collect_tmdb_names(db, task):
        add(name)
    add(str(getattr(task, "taskname", "") or ""))
    return keywords


def _latest_get(latest: Any, key: str) -> Any:
    if isinstance(latest, dict):
        return latest.get(key)
    return getattr(latest, key, None)



def _rewrite_shareurl_with_fid(shareurl: str, fid: str | None) -> str:
    url = str(shareurl or "").strip()
    f = str(fid or "").strip()
    if "yun.139.com" in url or "caiyun.139.com" in url:
        parsed = urlsplit(url)
        if parsed.fragment:
            frag_path, frag_query = (parsed.fragment.split("?", 1) + [""])[:2]
            frag_pairs = [(k, v) for k, v in parse_qsl(frag_query, keep_blank_values=True) if str(k).lower() != "fid"]
            if f and f not in ("0", "root"):
                frag_pairs.append(("fid", f))
            rebuilt_fragment = frag_path if not frag_pairs else f"{frag_path}?{urlencode(frag_pairs)}"
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, rebuilt_fragment)).strip()
        query_pairs = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if str(k).lower() != "fid"]
        if f and f not in ("0", "root"):
            query_pairs.append(("fid", f))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query_pairs), parsed.fragment)).strip()
    if not f or f == "0":
        head = url.split("#")[0].strip()
        return head
    if f in url:
        return url
    base = url.split("#")[0].strip()
    return f"{base}#/list/share/{f}"


def _pick_drive_type(db: Session, task: Task) -> str | None:
    account_name = str(getattr(task, "account_name", "") or "").strip()
    if account_name:
        row = db.execute(select(DriveAccount.drive_type).where(DriveAccount.name == account_name)).scalars().first()
        if row:
            dt = str(row or "").strip()
            return dt or None
    dt2 = AdapterRegistry.detect_drive_type(str(getattr(task, "shareurl", "") or ""))
    return None if not dt2 else str(dt2)


def repair_banned_drama_tasks(
    db: Session,
    *,
    task_ids: set[int] | None = None,
    audit_actor: object = None,
    audit_source: str = audit.SOURCE_AUTO,
) -> dict:
    """修复封禁/失效的追剧任务分享链接。task_ids 非空时仅处理指定任务（单任务手动运行后触发）。"""
    debug = _debug_enabled()
    stmt = select(Task).where(Task.enabled.is_(True), Task.task_type == "drama")
    if task_ids:
        stmt = stmt.where(Task.id.in_([int(x) for x in task_ids]))
    rows = db.execute(stmt.order_by(Task.id.asc())).scalars().all()
    logger.info("[repair] start scanned=%s", len(rows))
    if debug:
        logger.debug(f"[repair] scanned_rows={len(rows)}")
    invalid_shareurls = list_invalid_shareurls(db, shareurls=[str(getattr(t, "shareurl", "") or "").strip() for t in rows])
    logger.info("[repair] invalid_shareurls_matched=%s", len(invalid_shareurls))
    if debug:
        logger.debug(f"[repair] invalid_shareurls_matched={len(invalid_shareurls)}")
    targets: list[Task] = []
    for task in rows:
        task_id = int(getattr(task, "id", 0) or 0)
        taskname = str(getattr(task, "taskname", "") or "")
        ban = str(getattr(task, "shareurl_ban", "") or "").strip()
        shareurl = str(getattr(task, "shareurl", "") or "").strip()
        is_invalid = bool(shareurl and shareurl in invalid_shareurls)
        if not ban and not is_invalid:
            if debug:
                logger.debug(f"[repair] skip task_id={task_id} name={taskname} reason=no_ban_and_not_invalid")
            continue
        tmdb_media_type = str(getattr(task, "tmdb_media_type", "") or "").strip().lower()
        tmdb_id = getattr(task, "tmdb_id", None)
        if tmdb_media_type != "tv":
            if debug:
                logger.debug(
                    f"[repair] skip task_id={task_id} name={taskname} reason=tmdb_media_type_not_tv tmdb_media_type={tmdb_media_type}"
                )
            continue
        if tmdb_id is None:
            if debug:
                logger.debug(f"[repair] skip task_id={task_id} name={taskname} reason=tmdb_id_missing")
            continue
        if debug:
            logger.debug(f"[repair] target task_id={task_id} name={taskname} ban={ban!s} is_invalid={is_invalid} shareurl={shareurl}")
        targets.append(task)

    if not targets:
        if debug:
            logger.debug("[repair] no_targets")
        logger.info("[repair] done checked=0 repaired=0 targets=0")
        return {"checked": 0, "repaired": 0, "items": []}

    logger.info("[repair] targets=%s", len(targets))
    repaired: list[dict] = []
    db_changed = False

    for task in targets:
        try:
            task_id = int(getattr(task, "id", 0) or 0)
            taskname = str(getattr(task, "taskname", "") or "")
            old_shareurl = str(getattr(task, "shareurl", "") or "").strip()
            drive_type = _pick_drive_type(db, task)
            if not drive_type:
                if debug:
                    logger.debug(f"[repair] skip task_id={task_id} name={taskname} reason=drive_type_unknown")
                logger.info("[repair] skip task_id=%s name=%s reason=drive_type_unknown", task_id, taskname)
                continue
            if debug:
                logger.debug(f"[repair] task_id={task_id} name={taskname} drive_type={drive_type} old_shareurl={old_shareurl}")
            logger.info(
                "[repair] process task_id=%s name=%s drive_type=%s ban=%s",
                task_id,
                taskname,
                drive_type,
                str(getattr(task, "shareurl_ban", "") or "").strip(),
            )
            if str(drive_type) == "115":
                update_result = resolve_drama_shareurl_update(db, task, respect_toggle=False)
                if bool(update_result.get("db_changed")):
                    db_changed = True
                if not bool(update_result.get("updated")):
                    if debug:
                        logger.debug(
                            f"[repair] task_id={task_id} skip_115_update reason={str(update_result.get('reason') or '')}"
                        )
                    logger.info(
                        "[repair] skip task_id=%s name=%s reason=%s",
                        task_id,
                        taskname,
                        str(update_result.get("reason") or "115_no_update"),
                    )
                    continue
                db_changed = True
                repaired.append(
                    {
                        "task_id": int(getattr(task, "id", 0) or 0),
                        "taskname": str(getattr(task, "taskname", "") or ""),
                        "drive_type": drive_type,
                        "old_shareurl": str(update_result.get("old_shareurl") or old_shareurl),
                        "new_shareurl": str(update_result.get("new_shareurl") or ""),
                        "season": update_result.get("season"),
                        "episode": update_result.get("episode"),
                        "size": update_result.get("size"),
                    }
                )
                logger.info(
                    "[repair] repaired task_id=%s name=%s old=%s new=%s",
                    task_id,
                    taskname,
                    old_shareurl,
                    str(update_result.get("new_shareurl") or ""),
                )
                continue

            match_names = _pick_match_names(db, task)
            suggestions: list[dict] = []
            candidate_urls: list[str] = []
            candidate_titles: dict[str, str] = {}
            seen: set[str] = set()
            removed_same = 0
            removed_mismatch = 0
            removed_empty = 0
            removed_title_mismatch = 0
            mismatch_pool: list[dict] = []
            last_kw = ""
            last_msg = None
            for kw in _pick_search_keywords(db, task):
                last_kw = kw
                # 搜索阶段即限定当前任务的网盘类型，修复只能换同盘链接
                suggestions, changed, last_msg = fetch_task_suggestions(db, keyword=kw, deep=1, drive_type=drive_type)
                if changed:
                    db_changed = True
                if debug:
                    logger.debug(
                        f"[repair] task_id={task_id} keyword={kw} suggestions_count={len(suggestions or [])} msg={str(last_msg or '')}"
                    )
                for item in suggestions or []:
                    url = str((item or {}).get("shareurl") or "").strip()
                    if not url:
                        removed_empty += 1
                        continue
                    if url in seen:
                        continue
                    if old_shareurl and url == old_shareurl:
                        if debug:
                            logger.debug(f"[repair] task_id={task_id} skip_candidate reason=same_as_old url={url}")
                        removed_same += 1
                        continue
                    dt = AdapterRegistry.detect_drive_type(url)
                    if dt != drive_type:
                        if debug:
                            logger.debug(
                                f"[repair] task_id={task_id} skip_candidate reason=drive_type_mismatch url={url} dt={dt} expected={drive_type}"
                            )
                        removed_mismatch += 1
                        continue
                    title = str((item or {}).get("taskname") or (item or {}).get("content") or "").strip()
                    if match_names and not title_matches_names(title, match_names):
                        if debug:
                            logger.debug(
                                f"[repair] task_id={task_id} skip_candidate reason=title_mismatch title={title} names={match_names}"
                            )
                        removed_title_mismatch += 1
                        mismatch_pool.append({"shareurl": url, "taskname": title})
                        continue
                    seen.add(url)
                    candidate_urls.append(url)
                    candidate_titles[url] = title
                    if len(candidate_urls) >= 25:
                        break
                if candidate_urls:
                    break
            if not candidate_urls and mismatch_pool and match_names and is_vector_fallback_enabled():
                pool_titles = [str(x.get("taskname") or "") for x in mismatch_pool]
                for index, score in vector_recall(pool_titles, match_names):
                    _season, episode = extract_progress(pool_titles[index])
                    if episode is None:
                        continue
                    url = str(mismatch_pool[index].get("shareurl") or "").strip()
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    candidate_urls.append(url)
                    candidate_titles[url] = pool_titles[index]
                    logger.info(
                        "[repair] vector_fallback task_id=%s score=%s title=%s url=%s",
                        task_id,
                        round(score, 4),
                        pool_titles[index],
                        url,
                    )
                    if len(candidate_urls) >= 25:
                        break
            logger.info(
                "[repair] suggestions task_id=%s keyword=%s count=%s msg=%s",
                task_id,
                last_kw,
                len(suggestions or []),
                str(last_msg or ""),
            )
            if not candidate_urls:
                if debug:
                    logger.debug(f"[repair] task_id={task_id} no_candidate_urls")
                logger.info(
                    "[repair] skip task_id=%s name=%s reason=no_candidate_urls suggestions=%s removed_same=%s removed_mismatch=%s removed_empty=%s removed_title_mismatch=%s",
                    task_id,
                    taskname,
                    len(suggestions or []),
                    removed_same,
                    removed_mismatch,
                    removed_empty,
                    removed_title_mismatch,
                )
                continue
            if debug:
                logger.debug(f"[repair] task_id={task_id} candidate_urls={candidate_urls}")
            logger.info("[repair] candidate_urls task_id=%s count=%s", task_id, len(candidate_urls))

            batch_out, batch_changed = preview_share_batch(db, SharePreviewBatchIn(shareurls=candidate_urls, account_name=None))
            if batch_changed:
                db_changed = True
            if debug:
                ok_count = sum(1 for x in (batch_out.items or []) if bool(getattr(x, "ok", False)))
                logger.debug(f"[repair] task_id={task_id} preview_items={len(batch_out.items or [])} ok={ok_count}")
                for x in batch_out.items or []:
                    latest = getattr(x, "latest_video", None)
                    season = _latest_get(latest, "season") if latest is not None else None
                    episode = _latest_get(latest, "episode") if latest is not None else None
                    size = _latest_get(latest, "size") if latest is not None else None
                    logger.debug(
                        f"[repair] preview ok={bool(getattr(x,'ok',False))} url={str(getattr(x,'shareurl','') or '')} "
                        f"msg={str(getattr(x,'message', '') or '')} resolved_pdir_fid={str(getattr(x,'resolved_pdir_fid','') or '')} "
                        f"latest=S{season}E{episode} size={size}"
                    )
            ok_count = sum(1 for x in (batch_out.items or []) if bool(getattr(x, "ok", False)))
            fail_messages = []
            for x in batch_out.items or []:
                if bool(getattr(x, "ok", False)):
                    continue
                msg = str(getattr(x, "message", "") or "").strip()
                if msg:
                    fail_messages.append(msg)
                if len(fail_messages) >= 3:
                    break
            logger.info(
                "[repair] preview task_id=%s items=%s ok=%s sample_errors=%s",
                task_id,
                len(batch_out.items or []),
                ok_count,
                " | ".join(fail_messages),
            )

            best = None
            best_key = None
            for row in batch_out.items or []:
                if not bool(getattr(row, "ok", False)):
                    continue
                latest = getattr(row, "latest_video", None)
                season = _latest_get(latest, "season") if latest is not None else None
                episode = _latest_get(latest, "episode") if latest is not None else None
                size = _latest_get(latest, "size") if latest is not None else None
                # 部分网盘（如百度）预览不返回季/集，用候选标题解析出的进度兵底，避免退化为任意选一条
                if season is None or episode is None:
                    title_season, title_episode = extract_progress(
                        candidate_titles.get(str(getattr(row, "shareurl", "") or "").strip(), "")
                    )
                    season = season if season is not None else title_season
                    episode = episode if episode is not None else title_episode
                if latest is None and episode is None:
                    continue
                key = (
                    1 if episode is not None else 0,
                    int(season or 0),
                    int(episode or 0),
                    int(size or 0),
                )
                if best_key is None or key > best_key:
                    best_key = key
                    best = row

            if best is None or best_key is None:
                if debug:
                    logger.debug(f"[repair] task_id={task_id} no_best_match")
                logger.info("[repair] skip task_id=%s name=%s reason=no_best_match", task_id, taskname)
                continue

            latest = best.latest_video
            new_shareurl = _rewrite_shareurl_with_fid(str(best.shareurl or ""), str(getattr(best, "resolved_pdir_fid", None) or ""))
            if debug:
                logger.debug(f"[repair] task_id={task_id} picked best_key={best_key} new_shareurl={new_shareurl}")
            task.shareurl = new_shareurl
            task.shareurl_ban = None
            db.flush()
            db_changed = True
            logger.info("[repair] repaired task_id=%s name=%s old=%s new=%s", task_id, taskname, old_shareurl, new_shareurl)

            repaired.append(
                {
                    "task_id": int(getattr(task, "id", 0) or 0),
                    "taskname": str(getattr(task, "taskname", "") or ""),
                    "drive_type": drive_type,
                    "old_shareurl": old_shareurl,
                    "new_shareurl": new_shareurl,
                    "season": _latest_get(latest, "season"),
                    "episode": _latest_get(latest, "episode"),
                    "size": _latest_get(latest, "size"),
                }
            )
        except Exception as e:
            logger.warning("[repair] error task_id=%s name=%s err=%s", int(getattr(task, "id", 0) or 0), str(getattr(task, "taskname", "") or ""), str(e))
            continue
        finally:
            time.sleep(random.uniform(0.2, 0.6))

    if not repaired:
        if db_changed:
            db.commit()
        if debug:
            logger.debug(f"[repair] done checked={len(targets)} repaired=0 db_changed={db_changed}")
        logger.info("[repair] done checked=%s repaired=0 db_changed=%s", len(targets), db_changed)
        return {"checked": len(targets), "repaired": 0, "items": []}

    db.commit()
    if debug:
        logger.debug(f"[repair] done checked={len(targets)} repaired={len(repaired)}")
    logger.info("[repair] done checked=%s repaired=%s", len(targets), len(repaired))
    lines: list[str] = []
    for item in repaired:
        s = item.get("season")
        e = item.get("episode")
        se = ""
        if s is not None and e is not None:
            se = f"S{int(s):02d}E{int(e):02d}"
        size = item.get("size")
        size_text = f" size={int(size)}" if size is not None else ""
        lines.append(f"✅《{item.get('taskname')}》 {se}{size_text}\n{item.get('new_shareurl')}")
    content = "🔧自动修复封禁分享链接：\n\n" + "\n\n".join(lines)
    try:
        send_runtime(db, DRAMA_NOTIFY_TITLE, content)
    except Exception:
        pass
    _audit_repair_items(repaired, actor=audit_actor, source=audit_source)
    return {"checked": len(targets), "repaired": len(repaired), "items": repaired}


def _audit_repair_items(repaired: list[dict], *, actor: object = None, source: str = audit.SOURCE_AUTO) -> None:
    """为每个成功修复的任务写一条自动换链审计。"""
    for item in repaired or []:
        try:
            taskname = str(item.get("taskname") or "")
            drive_type = str(item.get("drive_type") or "").strip()
            new_url = str(item.get("new_shareurl") or "")
            suffix = f"（{drive_type}）" if drive_type else ""
            audit.audit_log_standalone(
                actor=audit.actor_for_source(actor, source),
                action="task.shareurl_repair",
                summary=f"自动修复任务《{taskname}》的失效分享链接{suffix}",
                target_type="task",
                target_id=item.get("task_id"),
                target_name=taskname,
                source=source,
                detail=(f"新分享链接：{new_url}" if new_url else None),
                success=True,
            )
        except Exception as e:
            logger.debug("[audit] task.shareurl_repair 审计写入失败: %s", e)

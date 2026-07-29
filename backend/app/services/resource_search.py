from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import requests  # noqa: F401  测试与旧代码通过 rs.requests 打桩，保留导入
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.errors import bad_request
from app.db.session import engine
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount
from app.models.resource_search_source import ResourceSearchSource
from app.services.invalid_share_links import list_invalid_shareurls
from app.services.resource_search_providers import (  # noqa: F401  向后兼容再导出
    EXTERNAL_TIMEOUT,
    SUPPORTED_CLOUD_TYPES,
    CloudSaverClient,
    PanSouClient,
    ProviderResult,
    SearchProvider,
    _iso_to_cst,
    _log_debug,
    _normalize_drive_type,
    _pansou_cloud_type,
    get_provider,
    iter_providers,
    provider_keys,
    register_provider,
)


logger = logging.getLogger(__name__)

# 搜索源 key 列表由插件注册表驱动，新增搜索源只需注册 SearchProvider 插件
SOURCE_KEYS = provider_keys()


def _loads(value: str) -> dict[str, Any]:
    try:
        obj = json.loads(value or "")
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _dumps(value: dict[str, Any]) -> str:
    return json.dumps(value or {}, ensure_ascii=False)


def ensure_default_sources(db: Session) -> dict[str, ResourceSearchSource]:
    try:
        existing = {r.key: r for r in db.execute(select(ResourceSearchSource)).scalars().all()}
    except OperationalError as e:
        if "no such table: resource_search_sources" not in str(e):
            raise
        ResourceSearchSource.__table__.create(bind=engine, checkfirst=True)
        existing = {r.key: r for r in db.execute(select(ResourceSearchSource)).scalars().all()}
    changed = False
    for provider in iter_providers():
        key = provider.key
        if key in existing:
            continue
        row = ResourceSearchSource(key=key, enabled=bool(provider.default_enabled), config_json=_dumps({}))
        db.add(row)
        db.flush()
        existing[key] = row
        changed = True
    if changed:
        db.flush()
    return existing


def list_sources(db: Session) -> list[dict[str, Any]]:
    rows = ensure_default_sources(db)
    out: list[dict[str, Any]] = []
    for provider in iter_providers():
        row = rows[provider.key]
        cfg = _loads(row.config_json or "")
        item: dict[str, Any] = {"key": row.key, "enabled": bool(row.enabled), "server": None, "username": None, "password": None, "token": None}
        for f in provider.public_fields:
            item[f] = cfg.get(f) or None
        out.append(item)
    return out


def update_source(db: Session, key: str, payload: dict[str, Any]) -> ResourceSearchSource:
    key = str(key or "").strip()
    provider = get_provider(key)
    if provider is None:
        raise bad_request("RESOURCE_SEARCH_SOURCE_INVALID", "不支持的搜索源")

    rows = ensure_default_sources(db)
    row = rows[key]
    cfg = _loads(row.config_json or "")

    if "enabled" in payload and payload["enabled"] is not None:
        row.enabled = bool(payload["enabled"])

    for f in provider.config_fields:
        if f in payload and payload[f] is not None:
            cfg[f] = str(payload[f] or "").strip()

    for f in provider.secret_fields:
        if f in payload and payload[f] is not None:
            secret = str(payload[f] or "")
            if secret.strip():
                cfg[f] = secret

    row.config_json = _dumps(cfg)
    db.flush()
    return row


def _normalize_source_keys(sources: list[str] | str | None) -> set[str] | None:
    """归一化渠道过滤参数；返回 None 表示不过滤（全部启用的搜索源）。"""
    if sources is None:
        return None
    if isinstance(sources, str):
        parts = [x.strip() for x in sources.split(",")]
    else:
        parts = [str(x or "").strip() for x in sources]
    keys = {x.lower() for x in parts if x}
    keys = {x for x in keys if get_provider(x) is not None}
    return keys or None


def _normalize_drive_types(values: list[str] | str | None) -> list[str]:
    """归一化网盘类型集合（保序去重）。"""
    if values is None:
        return []
    if isinstance(values, str):
        parts = [x.strip() for x in values.split(",")]
    else:
        parts = [str(x or "").strip() for x in values]
    out: list[str] = []
    for p in parts:
        dt = _normalize_drive_type(p)
        if dt and dt not in out:
            out.append(dt)
    return out


def list_available_drive_types(db: Session) -> list[str]:
    """当前可用（enabled 且 runtime_status 非异常）的网盘账号类型集合。"""
    raw = (
        db.execute(
            select(DriveAccount.drive_type).where(
                DriveAccount.enabled.is_(True),
                or_(
                    DriveAccount.runtime_status == "active",
                    DriveAccount.runtime_status.is_(None),
                    DriveAccount.runtime_status == "",
                ),
            )
        )
        .scalars()
        .all()
    )
    return sorted({dt for dt in (_normalize_drive_type(x) for x in raw) if dt})


def fetch_task_suggestions(
    db: Session,
    keyword: str,
    deep: int,
    *,
    filter_invalid: bool = True,
    drive_type: str | None = None,
    drive_types: list[str] | str | None = None,
    sources: list[str] | str | None = None,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """聚合多渠道资源搜索。

    drive_type：单一强制网盘类型（已指定账号、或自动+已填分享链接推断出的类型）。
    drive_types：候选网盘类型集合；与 drive_type 均为空时默认取当前可用网盘账号类型，
    使搜索请求本身就只面向已有账号的网盘，而不是先宽搜再丢弃。
    """
    keyword = str(keyword or "").strip()
    if len(keyword) < 2:
        return ([], False, None)
    deep = deep or 0
    dt_filter = _normalize_drive_type(drive_type)
    source_filter = _normalize_source_keys(sources)

    enabled_drive_types = list_available_drive_types(db)
    if not enabled_drive_types:
        return ([], False, "没有可用的网盘账号（enabled=true 且 runtime_status=active），已隐藏不支持的资源")
    if dt_filter and dt_filter not in enabled_drive_types:
        return ([], False, f"指定网盘类型没有可用账号：{dt_filter}")

    requested_types = _normalize_drive_types(drive_types)
    if dt_filter:
        search_drive_types = [dt_filter]
    elif requested_types:
        search_drive_types = [x for x in requested_types if x in enabled_drive_types] or list(enabled_drive_types)
    else:
        search_drive_types = list(enabled_drive_types)
    allowed_drive_types = set(search_drive_types)

    _log_debug(
        "[suggestions] request",
        {
            "keyword": keyword,
            "deep": deep,
            "drive_type": dt_filter,
            "search_drive_types": search_drive_types,
            "sources": sorted(source_filter) if source_filter else None,
        },
    )

    rows = ensure_default_sources(db)
    configs = {p.key: _loads(rows[p.key].config_json or "") for p in iter_providers()}
    _log_debug(
        "[suggestions] sources",
        {p.key: {"enabled": bool(rows[p.key].enabled), "config": configs[p.key]} for p in iter_providers()},
    )

    active_providers = [
        p
        for p in iter_providers()
        if bool(rows[p.key].enabled) and (source_filter is None or p.key in source_filter)
    ]

    def _run_provider(provider: SearchProvider) -> tuple[str, ProviderResult]:
        try:
            result = provider.search(
                keyword,
                deep,
                drive_type=dt_filter,
                drive_types=search_drive_types,
                config=configs.get(provider.key),
            )
        except Exception:
            result = ProviderResult()
        return (provider.key, result)

    search_results: list[dict[str, Any]] = []
    new_tokens: dict[str, str] = {}
    if active_providers:
        with ThreadPoolExecutor(max_workers=max(1, len(active_providers))) as executor:
            futures = [executor.submit(_run_provider, p) for p in active_providers]
            for fut in as_completed(futures):
                try:
                    key, result = fut.result()
                except Exception:
                    continue
                if result.new_token:
                    new_tokens[key] = str(result.new_token)
                provider = get_provider(key)
                for item in result.items:
                    if not isinstance(item, dict):
                        continue
                    item.setdefault("source", provider.display_name if provider else key)
                    item["source_key"] = key
                    search_results.append(item)

    results: list[dict[str, Any]] = []
    link_set: set[str] = set()

    def _sort_key(x: dict[str, Any]) -> str:
        v = x.get("datetime")
        return str(v or "")

    search_results.sort(key=_sort_key, reverse=True)
    for item in search_results:
        url = str(item.get("shareurl") or "").strip()
        if not url or url in link_set:
            continue
        link_set.add(url)
        results.append(item)

    token_updated = False
    for key, token in new_tokens.items():
        cfg = configs.get(key) or {}
        cfg["token"] = token
        rows[key].config_json = _dumps(cfg)
        db.flush()
        token_updated = True

    filtered: list[dict[str, Any]] = []
    removed_by_accounts = 0
    removed_by_drive_type = 0
    for item in results:
        url = str(item.get("shareurl") or "").strip()
        if not url:
            continue
        dt = AdapterRegistry.detect_drive_type(url)
        if not dt or str(dt) not in enabled_drive_types:
            removed_by_accounts += 1
            continue
        if str(dt) not in allowed_drive_types:
            removed_by_drive_type += 1
            continue
        name = item.get("taskname") if item.get("taskname") else item.get("content", "")
        item['taskname'] = name
        filtered.append(item)

    message = None
    msg_parts: list[str] = []
    if source_filter:
        msg_parts.append(f"已限定搜索渠道：{', '.join(sorted(source_filter))}")
    if dt_filter:
        msg_parts.append(f"已限定网盘类型：{dt_filter}")
    elif removed_by_accounts or removed_by_drive_type:
        msg_parts.append(f"已按可用网盘账号过滤：{', '.join(sorted(allowed_drive_types))}")
    if msg_parts:
        message = "; ".join(msg_parts)

    if filter_invalid:
        invalid = list_invalid_shareurls(db, shareurls=[str(x.get("shareurl") or "").strip() for x in filtered])
        if invalid:
            filtered = [x for x in filtered if str(x.get("shareurl") or "").strip() not in invalid]
            extra = f"已过滤失效链接：{len(invalid)}"
            message = f"{message}; {extra}" if message else extra

    return (filtered, token_updated, message)


def verify_task_suggestions(
    db: Session,
    shareurls: list[str],
    *,
    account_name: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """验证搜索结果分享链接的有效性。

    复用 preview_share_batch（内部按网盘类型分组逐个探测并带随机延迟防限流），
    并在此基础上汇总最大视频大小标记与有效/失效统计。
    失效链接会由 preview_share_batch 落库，后续搜索自动过滤。
    """
    from app.schemas.task_browse import SharePreviewBatchIn
    from app.services.share_preview_batch import preview_share_batch

    urls = [str(x or "").strip() for x in (shareurls or [])]
    urls = list(dict.fromkeys(x for x in urls if x))
    if not urls:
        return ({"items": [], "total": 0, "valid": 0, "invalid": 0}, False)

    changed = False
    items: list[dict[str, Any]] = []
    # preview_share_batch 单次最多 50 条，超出时分批串行
    for i in range(0, len(urls), 50):
        batch = urls[i : i + 50]
        out, batch_changed = preview_share_batch(db, SharePreviewBatchIn(shareurls=batch, account_name=account_name))
        changed = changed or batch_changed
        for row in out.items:
            latest = row.latest_video.model_dump() if row.latest_video is not None else None
            size = int(latest.get("size") or 0) if latest else 0
            items.append(
                {
                    "shareurl": row.shareurl,
                    "drive_type": row.drive_type,
                    "ok": bool(row.ok),
                    "message": row.message,
                    "pdir_fid": row.pdir_fid or row.resolved_pdir_fid or None,
                    "max_file_size": size or None,
                    "latest_video": latest,
                    "is_largest": False,
                }
            )

    max_size = max((int(x.get("max_file_size") or 0) for x in items), default=0)
    if max_size > 0:
        for x in items:
            x["is_largest"] = int(x.get("max_file_size") or 0) == max_size

    valid = sum(1 for x in items if x["ok"])
    return ({"items": items, "total": len(items), "valid": valid, "invalid": len(items) - valid}, changed)

from __future__ import annotations
import json
import logging
import threading
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.extensions.runtime.adapter_registry import AdapterRegistry
from app.models.drive_account import DriveAccount


logger = logging.getLogger(__name__)

_persist_lock = threading.Lock()


def _merge_runtime_values(
    drive_type: str,
    config_json: str | None,
    cookie: str | None,
    runtime_config: dict[str, Any] | None,
) -> dict[str, Any]:

    current = AdapterRegistry.parse_config_json(drive_type, config_json, cookie)
    merged = dict(current)
    for key, value in (runtime_config or {}).items():
        if value is None and key in merged:
            continue
        if isinstance(value, str) and not value.strip() and isinstance(merged.get(key), str) and str(merged.get(key) or "").strip():
            continue
        merged[key] = value
    return AdapterRegistry.normalize_config(drive_type, merged)


def persist_adapter_runtime_config(
    drive_type: str,
    account_name: str | None,
    runtime_config: dict[str, Any] | str | None,
) -> bool:
    dt = str(drive_type or "").strip()
    if not dt:
        return False
    if isinstance(runtime_config, str):
        payload = AdapterRegistry.deserialize_cookie(dt, runtime_config)
    elif isinstance(runtime_config, dict):
        payload = dict(runtime_config)
    else:
        return False
    if not payload:
        return False

    name = str(account_name or "").strip()
    try:
        with _persist_lock, SessionLocal() as db:
            stmt = select(DriveAccount).where(DriveAccount.drive_type == dt)
            rows = db.execute(stmt).scalars().all()
            account = None
            if name:
                account = next((row for row in rows if str(row.name or "") == name), None)
            if account is None and len(rows) == 1:
                # 未提供账号名（如 cloud189 旧调用约定）时，仅在该类型只有一个账号时才可安全定位
                account = rows[0]
            if account is None:
                logger.warning(
                    "[credential_store] 未定位到账号，跳过凭证落库 drive_type=%s account=%s candidates=%s",
                    dt,
                    name or "<空>",
                    len(rows),
                )
                return False
            merged = _merge_runtime_values(dt, account.config_json, account.cookie, payload)
            account.config_json = json.dumps(merged, ensure_ascii=False)
            account.cookie = AdapterRegistry.serialize_config(dt, merged)
            db.commit()
            logger.info("[credential_store] 凭证已落库 drive_type=%s account=%s", dt, account.name)
            return True
    except Exception as exc:
        logger.warning(
            "[credential_store] 凭证落库失败 drive_type=%s account=%s err=%s",
            dt,
            name or "<空>",
            str(exc).strip() or type(exc).__name__,
        )
        return False


def make_config_saver(drive_type: str):
    def saver(value: dict[str, Any] | str, account_name: str | None = None) -> bool:
        return persist_adapter_runtime_config(drive_type, account_name, value)

    return saver


def install_adapter_config_savers() -> None:
    from app.extensions.adapters import aliyun_adapter, cloud189_adapter, pan123_adapter, xunlei_adapter

    xunlei_adapter.set_config_saver(make_config_saver("xunlei"))
    aliyun_adapter.set_config_saver(make_config_saver("aliyun"))
    cloud189_adapter.set_config_saver(make_config_saver("cloud189"))
    pan123_adapter.set_config_saver(make_config_saver("123pan"))
    logger.info("[credential_store] 已接入 token 落库回调: xunlei/aliyun/cloud189/123pan")

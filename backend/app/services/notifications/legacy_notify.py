"""精简通知：仅保留 WxPusher。"""
from __future__ import annotations

import json
import logging
import threading

import requests

_send_lock = threading.Lock()
logger = logging.getLogger(__name__)

push_config: dict = {}

DEFAULT_PUSH_CONFIG = {
    "HITOKOTO": False,
    "WXPUSHER_APP_TOKEN": "",
    "WXPUSHER_TOPIC_IDS": "",
    "WXPUSHER_UIDS": "",
}


def _result(channel: str, ok: bool, message: str | None = None) -> dict[str, object]:
    return {"channel": channel, "ok": bool(ok), "message": message}


def wxpusher_bot(title: str, content: str) -> dict[str, object]:
    if not push_config.get("WXPUSHER_APP_TOKEN"):
        return _result("wxpusher", False, "not_configured")

    url = "https://wxpusher.zjiecode.com/api/send/message"
    payload: dict = {
        "appToken": push_config.get("WXPUSHER_APP_TOKEN"),
        "content": f"{title}\n\n{content}",
        "contentType": 1,
    }
    topic_ids = str(push_config.get("WXPUSHER_TOPIC_IDS") or "").strip()
    uids = str(push_config.get("WXPUSHER_UIDS") or "").strip()
    if topic_ids:
        payload["topicIds"] = [int(x) for x in topic_ids.split(";") if str(x).strip().isdigit()]
    if uids:
        payload["uids"] = [x for x in uids.split(";") if str(x).strip()]

    try:
        response = requests.post(url=url, json=payload, timeout=15).json()
    except Exception as exc:
        return _result("wxpusher", False, str(exc))
    ok = response.get("code") == 1000
    return _result("wxpusher", ok, None if ok else json.dumps(response, ensure_ascii=False))


def add_notify_function():
    notify_function = []
    if push_config.get("WXPUSHER_APP_TOKEN") and (
        push_config.get("WXPUSHER_TOPIC_IDS") or push_config.get("WXPUSHER_UIDS")
    ):
        enabled_map = _get_channel_enabled_map()
        if enabled_map.get("wxpusher", True):
            notify_function.append(wxpusher_bot)
    return notify_function


def _get_channel_enabled_map() -> dict[str, bool]:
    raw = push_config.get("__channel_enabled")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, bool] = {}
    for key, value in raw.items():
        if isinstance(key, str):
            result[key] = bool(value)
    return result


def send(
    title: str,
    content: str,
    ignore_default_config: bool = False,
    channels: list[str] | None = None,
    **kwargs,
) -> list[dict[str, object]]:
    global push_config
    with _send_lock:
        if ignore_default_config:
            push_config = dict(kwargs)
        else:
            push_config = {**DEFAULT_PUSH_CONFIG, **kwargs}

        funcs = add_notify_function()
        if channels:
            allow = {str(c).strip().lower() for c in channels if str(c).strip()}
            funcs = [f for f in funcs if f.__name__.replace("_bot", "") in allow or "wxpusher" in allow]

        results: list[dict[str, object]] = []
        for fn in funcs:
            try:
                results.append(fn(title, content))
            except Exception as exc:
                logger.exception("notify channel failed: %s", fn.__name__)
                results.append(_result(fn.__name__, False, str(exc)))
        return results

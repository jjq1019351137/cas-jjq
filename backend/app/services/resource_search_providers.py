from __future__ import annotations

import abc
import base64
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import requests


EXTERNAL_TIMEOUT = (15, 200)
logger = logging.getLogger(__name__)

SUPPORTED_CLOUD_TYPES = {
    "quark",
    "pan123",
    "pan115",
    "cloud115",
    "uc",
    "tianyi",
    "cloud189",
    "aliyun",
    "xunlei",
    "baidupan",
    "baidu",
}


def _normalize_drive_type(value: str | None) -> str | None:
    v = str(value or "").strip()
    if not v:
        return None
    k = v.lower()
    mapping = {
        "pan115": "115",
        "cloud115": "115",
        "115": "115",
        "pan123": "123pan",
        "123pan": "123pan",
        "tianyi": "cloud189",
        "cloud189": "cloud189",
        "baidupan": "baidu",
        "baidu": "baidu",
        "quark": "quark",
        "uc": "uc",
        "aliyun": "aliyun",
        "xunlei": "xunlei",
    }
    return mapping.get(k) or k


def _pansou_cloud_type(value: str | None) -> str | None:
    dt = _normalize_drive_type(value)
    if not dt:
        return None
    mapping = {
        "115": "115",
        "123pan": "pan123",
        "cloud189": "tianyi",
        "baidu": "baiduPan",
        "quark": "quark",
        "uc": "uc",
        "aliyun": "aliyun",
        "xunlei": "xunlei",
        "cloud139": "mobile",
        "guangya": "guangya",
    }
    return mapping.get(dt)


_PANSOU_MERGED_KEY_ALIASES = {
    "tianyi": ("tianyi", "cloud189"),
    "pan115": ("pan115", "cloud115", "115"),
    "115": ("115", "pan115", "cloud115"),
    "pan123": ("pan123", "123pan"),
    "baiduPan": ("baiduPan", "baidupan", "baidu"),
    "mobile": ("mobile", "cloud139"),
}


def _pansou_cloud_types(values: list[str] | None) -> list[str]:
    """将一组项目内部网盘类型映射为 PanSou 的 cloud_types（保序去重）。"""
    out: list[str] = []
    for v in values or []:
        ct = _pansou_cloud_type(v)
        if ct and ct not in out:
            out.append(ct)
    return out


def _pansou_merged_keys(cloud_type: str) -> list[str]:
    keys = list(_PANSOU_MERGED_KEY_ALIASES.get(cloud_type, (cloud_type,)))
    lower = cloud_type.lower()
    if lower not in keys:
        keys.append(lower)
    return keys


# PanSou 默认覆盖的云盘类型（未指定网盘类型时使用）
DEFAULT_PANSOU_CLOUD_TYPES = ("quark", "pan123", "pan115", "uc", "tianyi", "aliyun", "xunlei", "baiduPan")


def _debug_enabled() -> bool:
    return os.getenv("DEBUG", "0").strip().lower() in {"1", "true", "yes", "y", "on"}


def _mask_secret(value: str, keep: int = 2) -> str:
    v = str(value or "").strip()
    if not v:
        return ""
    if len(v) <= keep:
        return "*" * len(v)
    return v[:keep] + "*" * (len(v) - keep)


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key = str(k).lower()
            if key in {"password", "passwd"}:
                out[k] = "***"
            elif key in {"token", "access_token", "refresh_token", "authorization"}:
                out[k] = _mask_secret(str(v), keep=4)
            elif key in {"cookie", "cookies"}:
                out[k] = "***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj


def _truncate_text(text: str, max_chars: int = 20000) -> str:
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2]
    tail = text[-max_chars // 2 :]
    return f"{head}\n... (truncated, total_chars={len(text)}) ...\n{tail}"


def _log_debug(label: str, payload: Any) -> None:
    if not (_debug_enabled() or logger.isEnabledFor(logging.DEBUG)):
        return
    try:
        text = json.dumps(_redact(payload), ensure_ascii=False, indent=2, default=str)
    except Exception:
        text = repr(_redact(payload))
    msg = f"{label}={_truncate_text(text)}"
    if _debug_enabled():
        logger.info(msg)
    else:
        logger.debug(msg)


def _iso_to_cst(iso_time_str: str) -> str:
    from datetime import datetime

    try:
        dt = datetime.fromisoformat(str(iso_time_str))
        dt_cst = dt if dt > datetime.now() else dt
        return dt_cst.strftime("%Y-%m-%d %H:%M:%S") if dt_cst.year >= 1970 else ""
    except Exception:
        return ""


class CloudSaverClient:
    def __init__(self, server: str):
        self.server = server.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def set_auth(self, username: str, password: str, token: str = "") -> None:
        self.username = username
        self.password = password
        self.token = token
        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})
        else:
            self.session.headers.pop("Authorization", None)

    def login(self) -> dict[str, Any]:
        url = f"{self.server}/api/user/login"
        _log_debug("[cloudsaver.login] request", {"url": url, "username": self.username})
        res = self.session.post(url, json={"username": self.username, "password": self.password}, timeout=EXTERNAL_TIMEOUT)
        data = res.json()
        _log_debug("[cloudsaver.login] response", {"status_code": res.status_code, "json": data})
        if data.get("success"):
            token = ((data.get("data") or {}).get("token")) or ""
            self.token = token
            self.session.headers.update({"Authorization": f"Bearer {token}"})
            return {"success": True, "token": token}
        return {"success": False, "message": data.get("message") or "CloudSaver 登录失败"}

    def search(self, keyword: str, last_message_id: str = "") -> dict[str, Any]:
        url = f"{self.server}/api/search"
        _log_debug("[cloudsaver.search] request", {"url": url, "keyword": keyword, "lastMessageId": last_message_id})
        res = self.session.get(url, params={"keyword": keyword, "lastMessageId": last_message_id})
        data = res.json()
        _log_debug("[cloudsaver.search] response", {"status_code": res.status_code, "json": data})
        if data.get("success"):
            return {"success": True, "data": data.get("data") or []}
        return {"success": False, "message": data.get("message") or "CloudSaver 搜索失败"}

    def auto_login_search(self, keyword: str) -> dict[str, Any]:
        if not getattr(self, "token", None):
            r = self.login()
            if not r.get("success"):
                return r
            token = r.get("token") or ""
            search = self.search(keyword)
            if search.get("success"):
                search["new_token"] = token
            return search

        search = self.search(keyword)
        if search.get("success"):
            return search
        r = self.login()
        if not r.get("success"):
            return search
        token = r.get("token") or ""
        search = self.search(keyword)
        if search.get("success"):
            search["new_token"] = token
        return search

    def clean_search_results(self, search_results: Any, keyword: str | None = None) -> list[dict[str, Any]]:
        links: list[dict[str, Any]] = []
        if not isinstance(search_results, list):
            return links
        link_set: set[str] = set()
        keyword = str(keyword or "").strip()

        def _strip_html(text: str) -> str:
            if not text:
                return ""
            t = str(text).replace('<mark class="highlight">', "").replace("</mark>", "")
            return re.sub(r"<[^>]+>", "", t)

        def _title_contains_keyword(title: str) -> bool:
            if not keyword:
                return True
            title = (_strip_html(title) or "").strip()
            if match := re.search(r"(名称|标题)[：:]?(.*)", title, re.DOTALL):
                title = (match.group(2) or "").strip()
            title_norm = re.sub(r"\s+", "", title).lower()
            tokens = [t for t in re.split(r"\s+", keyword) if t]
            return all(re.sub(r"\s+", "", t).lower() in title_norm for t in tokens)

        enable_filter = os.getenv("CLOUDSAVER_TITLE_FILTER", "1").strip() != "0"

        for ch in search_results:
            if not isinstance(ch, dict):
                continue
            channel = ch.get("channel") or ch.get("name") or ""
            for item in (ch.get("list") or []):
                if not isinstance(item, dict):
                    continue
                if enable_filter and not _title_contains_keyword(str(item.get("title") or "")):
                    continue
                title = _strip_html(item.get("title") or "").strip() or ""
                if keyword and not _title_contains_keyword(title):
                    continue
                desc = _strip_html(item.get("desc") or item.get("content") or "").strip() or ""
                tm = item.get("datetime") or item.get("time") or ""
                if tm:
                    tm = _iso_to_cst(str(tm))
                cloud_links = item.get("cloudLinks") or item.get("cloud_links") or []
                if not isinstance(cloud_links, list):
                    continue
                for cl in cloud_links:
                    if not isinstance(cl, dict):
                        continue
                    url = str(cl.get("url") or cl.get("link") or "").strip()
                    if not url or url in link_set:
                        continue
                    drive = str(cl.get("cloudType") or cl.get("type") or "").lower()
                    if drive and drive not in SUPPORTED_CLOUD_TYPES:
                        continue
                    link_set.add(url)
                    links.append(
                        {
                            "shareurl": url,
                            "taskname": title,
                            "content": desc,
                            "datetime": tm,
                            "channel": str(channel),
                            "source": "CloudSaver",
                        }
                    )
        return links


class PanSouClient:
    def __init__(self, server: str):
        self.server = server.rstrip("/")
        self.session = requests.Session()

    def search(
        self,
        keyword: str,
        refresh: bool = False,
        *,
        drive_type: str | None = None,
        drive_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """按指定网盘类型搜索。

        drive_type 为单一强制类型；drive_types 为候选类型集合（例如已有网盘账号类型）。
        两者均为空时回退到 PanSou 默认支持的全部类型。
        """
        try:
            url = f"{self.server}/api/search"
            wanted = [drive_type] if drive_type else list(drive_types or [])
            cloud_types = _pansou_cloud_types(wanted) or list(DEFAULT_PANSOU_CLOUD_TYPES)
            params = {
                "kw": keyword,
                # PanSou 仅支持逗号拼接的 cloud_types；重复查询参数只会生效第一个
                "cloud_types": ",".join(cloud_types),
                "res": "merge",
                "refresh": bool(refresh),
            }
            res = self.session.get(url, params=params, timeout=EXTERNAL_TIMEOUT)
            data = res.json()
            if data.get("code") != 0:
                return []
            merged = (data.get("data") or {}).get("merged_by_type") or {}
            if not isinstance(merged, dict):
                return []
            items: list[Any] = []
            # 按请求的每个类型汇总结果，避免只取单一类型遗漏其他可用网盘
            for ct in cloud_types:
                for k in _pansou_merged_keys(ct):
                    if isinstance(merged.get(k), list):
                        items.extend(merged.get(k) or [])
                        break
            return self.format_search_results(items)
        except Exception:
            return []

    def format_search_results(self, search_results: Any) -> list[dict[str, Any]]:
        if not isinstance(search_results, list):
            return []
        pattern = r"^(.*?)(?:[【\[]?(?:简介|介绍|描述)[】\]]?[:：]?)?(.*)$"
        out: list[dict[str, Any]] = []
        link_set: set[str] = set()
        for item in search_results:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or url in link_set:
                continue
            note = str(item.get("note") or "")
            tm = str(item.get("datetime") or "")
            if tm:
                tm = _iso_to_cst(tm)
            m = re.search(pattern, note, re.DOTALL)
            title = (m.group(1) if m else note).strip()
            content = (m.group(2) if m else "").strip()
            link_set.add(url)
            out.append(
                {
                    "shareurl": url,
                    "taskname": title,
                    "content": content,
                    "datetime": tm,
                    "channel": str(item.get("source") or ""),
                    "source": "PanSou",
                }
            )
        return out


@dataclass
class ProviderResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    new_token: str | None = None


class SearchProvider(abc.ABC):
    """资源搜索源插件基类。

    新增搜索源时实现本类并调用 register_provider 注册，
    无需修改 fetch_task_suggestions 主流程。
    """

    key: str = ""
    display_name: str = ""
    default_enabled: bool = False
    # 允许通过 update_source 写入的配置字段（明文字段）
    config_fields: tuple[str, ...] = ()
    # 仅在非空时写入且不通过 list_sources 回显的敏感字段
    secret_fields: tuple[str, ...] = ()
    # list_sources 对外回显的配置字段
    public_fields: tuple[str, ...] = ()

    @abc.abstractmethod
    def search(
        self,
        keyword: str,
        deep: int,
        *,
        drive_type: str | None = None,
        drive_types: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ProviderResult:
        """执行搜索。

        drive_type：单一强制网盘类型（已指定账号或已知分享链接类型）。
        drive_types：候选网盘类型集合（通常为当前可用网盘账号类型）。
        不支持按类型检索的源可忽略这两个参数，结果会在汇总层统一过滤。
        """
        ...


class NetSearchProvider(SearchProvider):
    key = "net"
    display_name = "Net"
    default_enabled = True

    def search(
        self,
        keyword: str,
        deep: int,
        *,
        drive_type: str | None = None,
        drive_types: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ProviderResult:
        try:
            base_url = base64.b64decode("aHR0cHM6Ly9wYW5zZWFyY2guMTIzY2YudG9w").decode()
            url = f"{base_url}/task_suggestions"
            r = requests.get(url, params={"q": keyword.lower(), "d": str(deep)}, timeout=EXTERNAL_TIMEOUT)
            data = r.json()
            if isinstance(data, dict):
                items = data.get("data") if isinstance(data.get("data"), list) else []
                return ProviderResult(items=[x for x in items if isinstance(x, dict)])
            return ProviderResult()
        except Exception:
            return ProviderResult()


class CloudSaverProvider(SearchProvider):
    key = "cloudsaver"
    display_name = "CloudSaver"
    config_fields = ("server", "username", "token")
    secret_fields = ("password",)
    public_fields = ("server", "username", "token")

    def search(
        self,
        keyword: str,
        deep: int,
        *,
        drive_type: str | None = None,
        drive_types: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ProviderResult:
        try:
            cfg = config or {}
            server = str(cfg.get("server") or "").strip()
            username = str(cfg.get("username") or "").strip()
            password = str(cfg.get("password") or "")
            token = str(cfg.get("token") or "")
            if not (server and username and password):
                return ProviderResult()
            cs = CloudSaverClient(server)
            cs.set_auth(username=username, password=password, token=token)
            search = cs.auto_login_search(keyword.lower())
            if not search.get("success"):
                return ProviderResult()
            new_token = str(search.get("new_token") or "") or None
            _log_debug("[cloudsaver.search] raw_data", search.get("data"))
            results = cs.clean_search_results(search.get("data"), keyword=keyword.lower())
            _log_debug("[cloudsaver.search] cleaned_results", {"count": len(results), "items": results[:20]})
            return ProviderResult(items=results, new_token=new_token)
        except Exception:
            return ProviderResult()


class PanSouProvider(SearchProvider):
    key = "pansou"
    display_name = "PanSou"
    config_fields = ("server",)
    public_fields = ("server",)

    def search(
        self,
        keyword: str,
        deep: int,
        *,
        drive_type: str | None = None,
        drive_types: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> ProviderResult:
        try:
            cfg = config or {}
            server = str(cfg.get("server") or "").strip()
            if not server:
                return ProviderResult()
            ps = PanSouClient(server)
            return ProviderResult(
                items=ps.search(keyword.lower(), refresh=deep == 1, drive_type=drive_type, drive_types=drive_types)
            )
        except Exception:
            return ProviderResult()


_PROVIDERS: dict[str, SearchProvider] = {}


def register_provider(provider: SearchProvider) -> None:
    key = str(provider.key or "").strip()
    if not key:
        raise ValueError("SearchProvider.key 不能为空")
    _PROVIDERS[key] = provider


def get_provider(key: str) -> SearchProvider | None:
    return _PROVIDERS.get(str(key or "").strip())


def iter_providers() -> list[SearchProvider]:
    return list(_PROVIDERS.values())


def provider_keys() -> tuple[str, ...]:
    return tuple(_PROVIDERS.keys())


register_provider(NetSearchProvider())
register_provider(CloudSaverProvider())
register_provider(PanSouProvider())

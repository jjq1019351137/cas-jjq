import hashlib
import json
import logging
import posixpath
import random
import re
import time
from typing import Any
from urllib.parse import quote, unquote, urlencode, urljoin

import requests


logger = logging.getLogger(__name__)


class Fnv_refresh_v2:
    plugin_name = "fnv_refresh_v2"
    plugin_version = "py-compat"
    API_PREFIX = "/v/api/v1"
    DEFAULT_HEADERS = {
        "X-Trim-Client": "web",
        "X-Trim-Client-Version": "616",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    NO_SIGN_PATHS = {
        f"{API_PREFIX}/task/running",
        f"{API_PREFIX}/play/record",
        f"{API_PREFIX}/subtitle/upload",
    }
    NO_SIGN_PREFIXES = (
        f"{API_PREFIX}/sys/img/",
        f"{API_PREFIX}/img/",
        f"{API_PREFIX}/concat/",
        f"{API_PREFIX}/media/",
    )

    default_config = {
        "tips": "填写 endpoint、mount_quark 后即可启用；secret/api_key 可手动指定（自动提取失败时兜底）；token/long_token/fnv_token 可选。",
        "endpoint": "",
        "username": "",
        "password": "",
        "mount_quark": "",
        "remove_useless_wait": 180,
        "token": "",
        "long_token": "",
        "secret": "",
        "api_key": "",
        "fnv_token": "",
    }

    default_task_config: dict[str, Any] = {}

    def __init__(self, **kwargs):
        self.plugin_name = self.__class__.plugin_name
        self.session = requests.Session()
        self.session.headers.update(self.DEFAULT_HEADERS)
        self.is_active = False
        self.api_key = ""
        self.app_name = "trimemedia-web"
        self._discovery_attempted = False
        self._login_attempted = False
        # 最近一次签名的明细，接口返回 invalid sign 时随告警日志一并输出，便于定位
        self._last_sign_debug: dict[str, Any] = {}

        for key, value in self.default_config.items():
            setattr(self, key, kwargs.get(key, value))

        self.endpoint = self._normalize_endpoint(self.endpoint)
        self.mount_quark = self._normalize_path(self.mount_quark)
        self.remove_useless_wait = self._as_int(self.remove_useless_wait, default=180)

        if not self.endpoint or not self.mount_quark:
            logger.warning("%s: 缺少 endpoint 或 mount_quark，插件未激活", self.plugin_name)
            return

        self.is_active = self._bootstrap_runtime_auth(force=False)
        logger.info(
            "%s: 配置状态 endpoint=%s mount_quark=%s secret=%s api_key=%s fnv_token=%s token=%s long_token=%s",
            self.plugin_name,
            self.endpoint,
            self.mount_quark,
            self._mask(self.secret),
            self._mask(self.api_key),
            self._mask(self.fnv_token),
            self._mask(self.token),
            self._mask(self.long_token),
        )
        if self.is_active:
            logger.info("%s: 插件已激活", self.plugin_name)
        else:
            logger.warning(
                "%s: 插件未激活，需提供可用的 fnv_token 或 username/password",
                self.plugin_name,
            )

    def run(self, task, **_kwargs):
        if not self.is_active:
            return task

        target_path = self._build_target_path(task.get("savepath"))
        if not target_path:
            return task

        library_id = self._get_library_id(target_path)
        if not library_id:
            logger.warning("%s: 未找到与路径匹配的媒体库 %s", self.plugin_name, target_path)
            return task

        if self._scan_library(library_id, target_path):
            logger.info("%s: 已触发飞牛影视刷新 %s", self.plugin_name, target_path)
            if self.remove_useless_wait >= 0:
                self._remove_useless()
        return task

    def _bootstrap_runtime_auth(self, *, force: bool) -> bool:
        if not self.endpoint:
            return False

        if force or not self._discovery_attempted:
            self._discovery_attempted = True
            self._extract_signing_keys()

        if self.username and self.password and (force or not self.fnv_token):
            if force or not self._login_attempted:
                self._login_attempted = True
                self._login()

        return bool(self.fnv_token)

    def _extract_signing_keys(self) -> None:
        # 保存预配置值作为兜底：不同部署的 secret/api_key 不同，
        # 必须优先从当前部署的前端 JS 中提取，预配值仅在提取失败时使用
        pre_secret = self.secret
        pre_api_key = self.api_key
        if pre_secret and pre_api_key:
            logger.debug(
                "%s: 已预配签名信息，仍尝试从前端 JS 提取以确保匹配当前部署 secret=%s api_key=%s",
                self.plugin_name,
                self._mask(pre_secret),
                self._mask(pre_api_key),
            )
            # 清空以强制提取
            self.secret = ""
            self.api_key = ""
        try:
            js_files = self._discover_js_files()
        except Exception as exc:
            logger.warning("%s: 获取前端入口 JS 失败 %s", self.plugin_name, exc)
            return
        logger.debug("%s: 发现入口 JS %s 个: %s", self.plugin_name, len(js_files), js_files)

        # 记录每个文件的提取尝试结果，用于诊断
        extraction_log: list[dict[str, Any]] = []

        for js_url in js_files:
            try:
                js_text = self._fetch_text(js_url)
            except Exception as exc:
                logger.debug("%s: 读取入口 JS 失败 %s %s", self.plugin_name, js_url, exc)
                continue
            file_log: dict[str, Any] = {"url": js_url, "size": len(js_text)}
            extracted_secret = self._extract_secret(js_text)
            if extracted_secret:
                self.secret = extracted_secret
                file_log["secret"] = True
                logger.info("%s: 从 %s 提取到 secret=%s", self.plugin_name, js_url, self._mask(self.secret))
            extracted_api_key = self._extract_api_key(js_text)
            if extracted_api_key:
                self.api_key = extracted_api_key
                file_log["api_key"] = True
                logger.info("%s: 从 %s 提取到 api_key=%s", self.plugin_name, js_url, self._mask(self.api_key))
            if self.secret and self.api_key:
                return
            extraction_log.append(file_log)

        for js_url in js_files:
            try:
                js_text = self._fetch_text(js_url)
                chunk_urls = self._extract_imported_chunks(js_url, js_text)
            except Exception as exc:
                logger.debug("%s: 读取 chunk 索引失败 %s %s", self.plugin_name, js_url, exc)
                continue
            for chunk_url in chunk_urls:
                try:
                    chunk_text = self._fetch_text(chunk_url)
                except Exception as exc:
                    logger.debug("%s: 读取 chunk 失败 %s %s", self.plugin_name, chunk_url, exc)
                    continue
                chunk_log: dict[str, Any] = {"url": chunk_url, "size": len(chunk_text)}
                extracted_secret = self._extract_secret(chunk_text)
                if extracted_secret:
                    self.secret = extracted_secret
                    chunk_log["secret"] = True
                    logger.info("%s: 从 chunk %s 提取到 secret=%s", self.plugin_name, chunk_url, self._mask(self.secret))
                extracted_api_key = self._extract_api_key(chunk_text)
                if extracted_api_key:
                    self.api_key = extracted_api_key
                    chunk_log["api_key"] = True
                    logger.info("%s: 从 chunk %s 提取到 api_key=%s", self.plugin_name, chunk_url, self._mask(self.api_key))
                if self.secret and self.api_key:
                    return
                extraction_log.append(chunk_log)

        missing = []
        if not self.secret:
            missing.append("secret")
        if not self.api_key:
            missing.append("api_key")
        if missing:
            scanned_files = [e["url"].rsplit("/", 1)[-1] for e in extraction_log]
            logger.warning(
                "%s: 自动提取签名信息失败，缺少 %s。已扫描 %d 个 JS 文件: %s。"
                "前端代码结构可能因版本/部署不同而变化，请在配置中手动指定 secret 和 api_key。",
                self.plugin_name,
                "/".join(missing),
                len(extraction_log),
                scanned_files[:5],
            )

        # 提取失败时，用预配置值兜底
        if not self.secret and pre_secret:
            self.secret = pre_secret
            logger.info("%s: secret 提取失败，回退使用预配置值 %s", self.plugin_name, self._mask(self.secret))
        if not self.api_key and pre_api_key:
            self.api_key = pre_api_key
            logger.info("%s: api_key 提取失败，回退使用预配置值 %s", self.plugin_name, self._mask(self.api_key))

    def _discover_js_files(self) -> list[str]:
        html = self._fetch_text(f"{self.endpoint}/v/")
        scripts = re.findall(r'src="([^"]+\.js)"', html)
        return [urljoin(self.endpoint, item) for item in scripts]

    def _fetch_text(self, url: str) -> str:
        response = self.session.get(url, timeout=5)
        response.raise_for_status()
        return response.text

    def _login(self) -> bool:
        if not self.username or not self.password:
            return False

        payload = {
            "username": self.username,
            "password": self._sha256(str(self.password)),
            "app_name": self.app_name or "trimemedia-web",
        }
        url = f"{self.endpoint}/v/api/v2/user/loginByPassword"
        headers = {
            "Content-Type": "application/json",
            **self._cookie_headers(),
        }
        try:
            response = self.session.post(
                url,
                headers=headers,
                data=self._serialize_data(payload).encode("utf-8"),
                timeout=5,
            )
            response.raise_for_status()
            payload_data = response.json()
        except Exception as exc:
            logger.warning("%s: 登录失败 %s", self.plugin_name, exc)
            return False

        if not isinstance(payload_data, dict) or payload_data.get("code") != 0:
            logger.warning(
                "%s: 登录失败 %s",
                self.plugin_name,
                self._payload_message(payload_data),
            )
            return False

        token = self._find_first(payload_data.get("data"), {"token"})
        if not token:
            logger.warning("%s: 登录响应缺少 token", self.plugin_name)
            return False

        self.fnv_token = str(token)
        self.session.cookies.set("Trim-MC-token", self.fnv_token)
        return True

    def _request(
        self,
        method: str,
        rel_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        quiet: bool = False,
        retry_auth: bool = True,
    ) -> dict[str, Any] | None:
        if not self.fnv_token and self.username and self.password:
            self._bootstrap_runtime_auth(force=False)

        url = f"{self.endpoint.rstrip('/')}{rel_url}"
        headers = self._build_headers(method=method, rel_url=rel_url, params=params, data=data)
        body_text = self._serialize_data(data if data is not None else {})
        logger.debug(
            "%s: 发起请求 %s %s params=%s body=%s authx=%s",
            self.plugin_name,
            method.upper(),
            rel_url,
            params,
            body_text,
            headers.get("authx", "<无签名>"),
        )
        try:
            response = self.session.request(
                method.upper(),
                url,
                headers=headers,
                params=params,
                data=body_text.encode("utf-8"),
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            if not quiet:
                body_preview = ""
                resp = locals().get("response")
                if resp is not None:
                    body_preview = f" http_status={resp.status_code} 响应体={resp.text[:300]}"
                logger.warning("%s: 请求失败 %s %s%s", self.plugin_name, rel_url, exc, body_preview)
            if retry_auth and self.username and self.password and self._bootstrap_runtime_auth(force=True):
                return self._request(
                    method,
                    rel_url,
                    params=params,
                    data=data,
                    quiet=quiet,
                    retry_auth=False,
                )
            return None

        if not isinstance(payload, dict):
            if not quiet:
                logger.warning("%s: 接口返回非字典响应 %s", self.plugin_name, rel_url)
            return None

        if self._is_auth_failure(payload):
            if retry_auth and self.username and self.password and self._bootstrap_runtime_auth(force=True):
                return self._request(
                    method,
                    rel_url,
                    params=params,
                    data=data,
                    quiet=quiet,
                    retry_auth=False,
                )
            if not quiet:
                logger.warning("%s: 接口认证失败 %s %s", self.plugin_name, rel_url, self._payload_message(payload))
            return payload

        if payload.get("code") not in (0, None) and not quiet:
            message = self._payload_message(payload)
            logger.warning(
                "%s: 接口返回异常 %s %s",
                self.plugin_name,
                rel_url,
                message,
            )
            if "sign" in message.lower():
                logger.warning(
                    "%s: 签名被拒，本次签名明细 %s",
                    self.plugin_name,
                    json.dumps(self._last_sign_debug, ensure_ascii=False),
                )
        return payload

    def _build_headers(
        self,
        *,
        method: str,
        rel_url: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
    ) -> dict[str, str]:
        headers = {
            **self.DEFAULT_HEADERS,
            **self._cookie_headers(),
        }
        if self.fnv_token:
            headers["Authorization"] = self.fnv_token
        needs_sign = self._needs_signature(rel_url, method)
        if needs_sign and self.secret and self.api_key:
            headers["authx"] = self._cse_sign(method, rel_url, params=params, data=data)
        elif needs_sign:
            # 需要签名但缺少密钥，后端大概率返回 invalid sign，明确提示缺什么
            missing = [name for name, val in (("secret", self.secret), ("api_key", self.api_key)) if not val]
            logger.warning(
                "%s: %s 需要签名但缺少 %s，未携带 authx，接口大概率报 invalid sign",
                self.plugin_name,
                rel_url,
                "/".join(missing),
            )
        else:
            logger.debug("%s: %s 在免签名名单，不携带 authx", self.plugin_name, rel_url)
        return headers

    def _cookie_headers(self) -> dict[str, str]:
        cookies: list[str] = []
        if self.token:
            cookies.append(f"fnos-token={self.token}")
        if self.long_token:
            cookies.append(f"fnos-long-token={self.long_token}")
        if self.fnv_token:
            cookies.append(f"Trim-MC-token={self.fnv_token}")
        return {"Cookie": "; ".join(cookies)} if cookies else {}

    def _get_library_id(self, target_path: str) -> str | None:
        payload = self._request("GET", f"{self.API_PREFIX}/mdb/list")
        libraries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(libraries, list) or not libraries:
            logger.warning(
                "%s: 获取媒体库列表失败或为空 code=%s msg=%s",
                self.plugin_name,
                payload.get("code") if isinstance(payload, dict) else None,
                self._payload_message(payload),
            )
            return None

        if len(libraries) == 1:
            return self._extract_guid(libraries[0])

        best_guid = None
        best_score = -1
        for item in libraries:
            guid = self._extract_guid(item)
            if not guid:
                continue
            for path_value in self._extract_path_candidates(item):
                if self._path_matches_library(target_path, path_value) and len(path_value) > best_score:
                    best_guid = guid
                    best_score = len(path_value)
        return best_guid

    def _scan_library(self, library_id: str, target_path: str) -> bool:
        payload = self._request(
            "POST",
            f"{self.API_PREFIX}/mdb/scan/{library_id}",
            data={"dir_list": [target_path]},
        )
        ok = bool(payload and payload.get("code") == 0)
        if not ok:
            logger.warning(
                "%s: 触发扫描失败 library_id=%s path=%s code=%s msg=%s",
                self.plugin_name,
                library_id,
                target_path,
                payload.get("code") if isinstance(payload, dict) else None,
                self._payload_message(payload),
            )
        return ok

    def _remove_useless(self) -> None:
        wait_time = self.remove_useless_wait
        for body in ({"wait_time": wait_time}, {"wait": wait_time}, {"seconds": wait_time}):
            payload = self._request("POST", f"{self.API_PREFIX}/task/removeUseless", data=body, quiet=True)
            if payload and payload.get("code") == 0:
                logger.info("%s: 已清理缺失媒体等待任务", self.plugin_name)
                return

    def _build_target_path(self, _savepath: str) -> str:
        mount_quark = self._normalize_path(self.mount_quark)
        if not mount_quark:
            return ""
        return mount_quark

    def _extract_guid(self, item: Any) -> str | None:
        candidates = self._find_all(item, {"guid", "id", "mdb_guid"})
        for value in candidates:
            if value:
                return str(value)
        return None

    def _extract_path_candidates(self, item: Any) -> list[str]:
        raw = self._find_all(
            item,
            {
                "dir",
                "dir_list",
                "path",
                "root_dir",
                "root_path",
                "mount_path",
                "library_path",
                "media_path",
                "folder",
            },
        )
        values: list[str] = []
        for value in raw:
            if isinstance(value, str) and value.startswith("/"):
                values.append(self._normalize_path(value))
            elif isinstance(value, list):
                for sub in value:
                    if isinstance(sub, str) and sub.startswith("/"):
                        values.append(self._normalize_path(sub))
        return list(dict.fromkeys(values))

    def _path_matches_library(self, target_path: str, library_path: str) -> bool:
        target = self._normalize_path(target_path)
        library = self._normalize_path(library_path)
        if not target or not library:
            return False
        if target == library:
            return True
        return target.startswith(library.rstrip("/") + "/")

    def _needs_signature(self, path: str, method: str) -> bool:
        if "/play/record" in path and method.upper() == "DELETE":
            return True
        if path in self.NO_SIGN_PATHS:
            return False
        return not any(path.startswith(prefix) for prefix in self.NO_SIGN_PREFIXES)

    def _cse_sign(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> str:
        nonce = str(random.randint(100000, 999999))
        timestamp = str(int(time.time() * 1000))
        body_hash = self._build_body_hash(method, data=data, params=params)
        sign_source = "_".join([self.secret, path, nonce, timestamp, body_hash, self.api_key])
        sign = self._md5(sign_source)
        self._last_sign_debug = {
            "method": method.upper(),
            "path": path,
            "nonce": nonce,
            "timestamp": timestamp,
            "body_hash": body_hash,
            "secret": self._mask(self.secret),
            "api_key": self._mask(self.api_key),
            "sign": sign,
            "params": params,
            "body": self._serialize_data(data),
        }
        logger.debug("%s: 生成签名 %s", self.plugin_name, json.dumps(self._last_sign_debug, ensure_ascii=False))
        return f"nonce={nonce}&timestamp={timestamp}&sign={sign}"

    def _build_body_hash(
        self,
        method: str,
        *,
        data: dict[str, Any] | None,
        params: dict[str, Any] | None,
    ) -> str:
        if method.upper() == "GET" and params:
            serialized = urlencode(sorted(params.items()), quote_via=quote)
            try:
                serialized = unquote(serialized)
            except Exception:
                pass
            return self._md5(serialized)
        return self._md5(self._serialize_data(data))

    def _is_auth_failure(self, payload: dict[str, Any]) -> bool:
        code = payload.get("code")
        if code in {-2, 401, 403}:
            return True
        message = self._payload_message(payload).lower()
        return "token" in message and ("invalid" in message or "expired" in message or "失效" in message)

    def _payload_message(self, payload: Any) -> str:
        if not isinstance(payload, dict):
            return str(payload)
        message = payload.get("msg") or payload.get("message") or payload.get("code")
        return str(message)

    def _find_first(self, value: Any, keys: set[str]) -> str | None:
        matches = self._find_all(value, keys)
        for item in matches:
            if item:
                return str(item)
        return None

    def _find_all(self, value: Any, keys: set[str]) -> list[Any]:
        hits: list[Any] = []
        if isinstance(value, dict):
            for key, sub in value.items():
                if key in keys:
                    hits.append(sub)
                hits.extend(self._find_all(sub, keys))
        elif isinstance(value, list):
            for item in value:
                hits.extend(self._find_all(item, keys))
        return hits

    def _extract_imported_chunks(self, entry_url: str, js_text: str) -> list[str]:
        imports = re.findall(r'from\s*["\']\./([^"\']+)["\']', js_text)
        base = entry_url.rsplit("/", 1)[0] + "/"
        return [base + item for item in imports if item.endswith(".js")]

    @staticmethod
    def _extract_secret(js_text: str) -> str | None:
        patterns = [
            r'\[\s*`([A-Za-z0-9+/=]{20,50})`\s*'
            r'(?:,\s*[a-zA-Z_$][\w$]*\s*){5}'
            r'\]\s*\.join\s*\(\s*`_`\s*\)',
            r'\[\s*`([A-Za-z0-9+/=]{20,50})`\s*'
            r'(?:,\s*[a-zA-Z_$][\w$]*\s*){5}'
            r'\]\s*\.join\s*\(\s*["\']_["\']',
            r'\[\s*["\']([A-Za-z0-9+/=]{20,50})["\']\s*'
            r'(?:,\s*[a-zA-Z_$][\w$]*\s*){5}'
            r'\]\s*\.join',
            r'\[`([A-Za-z0-9+/=]{20,50})`,\s*r,\s*s,\s*c,\s*o,\s*t\]\.join',
        ]
        for i, pat in enumerate(patterns):
            match = re.search(pat, js_text)
            if match:
                logger.debug("_extract_secret: 策略 %d 命中", i + 1)
                return match.group(1)
        return None

    @staticmethod
    def _extract_api_key(js_text: str) -> str | None:
        # ── 策略 1（最灵活）：Uint8Array 字节 + XOR + TextDecoder ──
        # API key 以 XOR 编码存储在 Uint8Array 中，解码公式：byte ^ xorKey
        # 变量名由 minifier 决定，不能硬编码
        strategies: list[tuple[str, re.Pattern]] = [
            # 策略 1: 通用模式 — Uint8Array([...])...任意变量 XOR 赋值...TextDecoder decode
            (
                "Uint8Array+XOR+TextDecoder",
                re.compile(
                    r'new\s+Uint8Array\(\s*\[([\d,\s]+)\]\s*\)'
                    r'.{0,200}?'
                    r'(\w+)\[\w+\]\s*=\s*(\w+)\[\w+\]\s*\^\s*(\d+)'
                    r'.{0,100}?'
                    r'TextDecoder',
                    re.DOTALL,
                ),
            ),
            # 策略 2: XOR 紧跟在 Uint8Array 后面，变量名任意
            (
                "Uint8Array+XOR-simple",
                re.compile(
                    r'new\s+Uint8Array\(\s*\[([\d,\s]+)\]\s*\)'
                    r'.{0,150}?'
                    r'\w+\[\w+\]\s*=\s*\w+\[\w+\]\s*\^\s*(\d+)',
                    re.DOTALL,
                ),
            ),
            # 策略 3: 原始模式（兼容旧版 minifier）
            (
                "legacy-t[n]=e[n]^",
                re.compile(
                    r'new\s+Uint8Array\(\[([\d,\s]+)\]\).*?t\[n\]=e\[n\]\^(\d+)',
                    re.DOTALL,
                ),
            ),
        ]
        for name, pat in strategies:
            match = pat.search(js_text)
            if not match:
                continue
            groups = match.groups()
            try:
                byte_str = groups[0]
                byte_values = [int(item.strip()) for item in byte_str.split(",") if item.strip()]
                # XOR key 是最后一个捕获组（数字）
                xor_key = int(groups[-1])
                decoded = bytes(value ^ xor_key for value in byte_values).decode("utf-8")
                # 基本合法性校验：API key 应该是可打印 ASCII
                if decoded and all(32 <= ord(c) < 127 for c in decoded):
                    logger.debug("_extract_api_key: 策略 %s 命中, xorKey=%d, len=%d", name, xor_key, len(decoded))
                    return decoded
            except Exception:
                continue

        for ref_match in re.finditer(r'\bapiKey\s*:\s*([a-zA-Z_$][\w$]*)', js_text):
            var_name = ref_match.group(1)
            scan_start = max(0, ref_match.start() - 3000)
            scan_region = js_text[scan_start:ref_match.start()]
            assign_pat = re.compile(
                rf'(?:^|[;{{,])\s*{re.escape(var_name)}\s*=\s*(["\'])'
                rf'([0-9A-Fa-f]{{8}}-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{4}}'
                rf'-[0-9A-Fa-f]{{4}}-[0-9A-Fa-f]{{12}})\1'
            )
            assign_match = assign_pat.search(scan_region)
            if assign_match:
                api_key_value = assign_match.group(2).upper()
                logger.debug(
                    "_extract_api_key: 策略 plain-uuid 命中, var=%s, len=%d",
                    var_name,
                    len(api_key_value),
                )
                return api_key_value

        return None

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        endpoint = str(endpoint or "").strip().rstrip("/")
        if not endpoint:
            return ""
        if "://" not in endpoint:
            endpoint = f"http://{endpoint}"
        return endpoint

    @staticmethod
    def _normalize_path(path: str) -> str:
        path = str(path or "").strip()
        if not path:
            return ""
        path = path.replace("\\", "/")
        if not path.startswith("/"):
            path = "/" + path
        normalized = posixpath.normpath(path)
        return "/" if normalized == "." else normalized

    @staticmethod
    def _as_int(value: Any, *, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _mask(value: Any) -> str:
        """敏感值打码：保留首尾各 4 位，便于比对是否配错而不泄露完整密钥"""
        text = str(value or "")
        if not text:
            return "<空>"
        if len(text) <= 8:
            return f"{text[:2]}***(len={len(text)})"
        return f"{text[:4]}...{text[-4:]}(len={len(text)})"

    @staticmethod
    def _sha256(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _md5(value: str) -> str:
        return hashlib.md5(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _serialize_data(data: Any) -> str:
        if isinstance(data, dict):
            return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        if isinstance(data, str):
            return data
        if not data:
            return ""
        return ""

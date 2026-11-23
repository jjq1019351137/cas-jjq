"""起始集数过滤：用重命名后的剧集号（如 S01E92）替代网盘文件 FID。

换链后 FID 会变，但集数锚点（SxxExx / Exx）可跨链接复用。
语义：转存「大于等于」起始集数的文件；无法识别集数的文件不做起始过滤。
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from typing import Any

from app.services.title_match import extract_progress

# S01E92 / s1e92 / S01.E92
_RE_SE = re.compile(r"[Ss](\d{1,2})\s*[.\-_ ]?\s*[Ee][Pp]?(\d{1,4})\b")
# 独立 E92 / Ep92（避免误吃年份）
_RE_E_ONLY = re.compile(r"(?<![A-Za-z0-9])[Ee][Pp]?(\d{1,4})\b")
# 纯数字锚点：92 / E92
_RE_BARE = re.compile(r"^[Ee]?(\d{1,4})$")


def format_episode_anchor(season: int | None, episode: int) -> str:
    ep = int(episode)
    if season is not None and int(season) > 0:
        return f"S{int(season):02d}E{ep:02d}"
    return f"E{ep}"


def parse_episode_anchor(value: str | None) -> tuple[int | None, int] | None:
    """解析起始锚点：支持 S01E92 / E92 / 92 / 任意含 SxxExx 的文件名。"""
    text = str(value or "").strip()
    if not text:
        return None
    stem = os.path.splitext(text)[0].strip()
    candidate = stem or text

    m = _RE_SE.search(candidate)
    if m:
        return int(m.group(1)), int(m.group(2))

    m = _RE_E_ONLY.search(candidate)
    if m:
        return None, int(m.group(1))

    m = _RE_BARE.match(candidate)
    if m:
        return None, int(m.group(1))

    season, episode = extract_progress(candidate)
    if episode is not None and int(episode) > 0:
        return (int(season) if season is not None and int(season) > 0 else None), int(episode)
    return None


def is_episode_anchor(value: str | None) -> bool:
    return parse_episode_anchor(value) is not None


def episode_key_from_renamed_name(renamed_name: str | None) -> tuple[int | None, int] | None:
    """从临时重命名结果提取（季, 集）。"""
    return parse_episode_anchor(renamed_name)


def resolve_start_episode_key(
    start_value: str | None,
    *,
    share_files: Iterable[dict[str, Any]] | None = None,
    rename_name: Callable[[str], str] | None = None,
    get_fid: Callable[[dict[str, Any]], str | None] | None = None,
    get_name: Callable[[dict[str, Any]], str | None] | None = None,
) -> tuple[int | None, int] | None:
    """解析任务里的 startfid 字段为集数锚点。

    优先按集数锚点直接解析；若是旧版网盘 FID，则在当前分享列表中定位文件，
    经重命名规则后再提取集数。找不到则返回 None（不按起始过滤）。
    """
    raw = str(start_value or "").strip()
    if not raw:
        return None

    direct = parse_episode_anchor(raw)
    if direct is not None:
        return direct

    if not share_files or rename_name is None or get_fid is None or get_name is None:
        return None

    for item in share_files:
        fid = str(get_fid(item) or "").strip()
        if not fid or fid != raw:
            continue
        origin = str(get_name(item) or "").strip()
        if not origin:
            return None
        try:
            renamed = str(rename_name(origin) or origin)
        except Exception:
            renamed = origin
        return episode_key_from_renamed_name(renamed)
    return None


def is_before_start_episode(
    file_key: tuple[int | None, int] | None,
    start_key: tuple[int | None, int] | None,
) -> bool:
    """文件集数是否严格小于起始锚点（起始集本身保留，即 >= 才转存）。"""
    if start_key is None or file_key is None:
        return False
    start_season, start_episode = start_key
    file_season, file_episode = file_key
    if start_season is not None and file_season is not None:
        return (int(file_season), int(file_episode)) < (int(start_season), int(start_episode))
    return int(file_episode) < int(start_episode)

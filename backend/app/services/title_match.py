from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

DEFAULT_MATCH_THRESHOLD = 0.85

_RE_EMOJI = re.compile(
    r"[\U0001F1E6-\U0001F1FF]"
    r"|[\U0001F300-\U0001F5FF]"
    r"|[\U0001F600-\U0001F64F]"
    r"|[\U0001F680-\U0001F6FF]"
    r"|[\U0001F700-\U0001F77F]"
    r"|[\U0001F780-\U0001F7FF]"
    r"|[\U0001F800-\U0001F8FF]"
    r"|[\U0001F900-\U0001F9FF]"
    r"|[\U0001FA00-\U0001FAFF]"
    r"|[\U00002600-\U000026FF]"
    r"|[\U00002700-\U000027BF]"
    r"|[\u200D\uFE0F]",
    re.UNICODE,
)
_RE_SOURCE_PREFIX = re.compile(
    r"^\s*[\(\[（【]?\s*(?:电视剧|剧集|连续剧|网剧|短剧|国剧|韩剧|日剧|美剧|英剧|台剧|泰剧|港剧|国产剧|动漫|动画|番剧|综艺|纪录片)\s*[\)\]）】]?\s*(?:名称|片名|剧名)?\s*[:：]?\s*",
    re.IGNORECASE,
)
_RE_NAME_LABEL = re.compile(r"(?:资源名称|资源|名称|片名|剧名)\s*[:：]\s*")
_RE_YEAR_BRACKETS = re.compile(r"[\(\[（【]\s*(?:19|20)\d{2}\s*[\)\]）】]")
_RE_YEAR_BARE = re.compile(r"(?<![0-9])(?:19|20)\d{2}(?![0-9])")
_RE_SEASON_EPISODE = re.compile(r"\bS(\d{1,3})\s*E(\d{1,4})\b", re.IGNORECASE)
_RE_SEASON_CN = re.compile(r"第\s*([0-9一二两三四五六七八九十]{1,3})\s*季")
_RE_SEASON_EN = re.compile(r"\bSeason\s*0*(\d{1,2})\b", re.IGNORECASE)
_RE_SEASON_S = re.compile(r"\bS0*(\d{1,2})\b(?!\s*E\d)", re.IGNORECASE)
_RE_EPISODE_RANGE_CN = re.compile(
    r"(?:更新至|更至|连载至|已更新?至)\s*第?\s*0*(\d{1,4})\s*集?"
    r"|(?:已)?更新?\s*第?\s*0*(\d{1,4})\s*集?"
)
_RE_EPISODE_SE_RANGE = re.compile(r"\bS(\d{1,3})E\d{1,4}\s*-\s*E?(\d{1,4})\b", re.IGNORECASE)
_RE_EPISODE_TOTAL_CN = re.compile(r"(?:全|共)\s*0*(\d{1,4})\s*集|0*(\d{1,4})\s*集\s*全")
_RE_EPISODE_ONLY = re.compile(r"(?:\bEP(?:ISODE)?|第)\s*0*(\d{1,4})\s*(?:集)?\b", re.IGNORECASE)
_RE_EPISODE_BARE_CN = re.compile(r"(?<![0-9第])0*(\d{1,4})\s*集")
_RE_EPISODE_BARE_NUM = re.compile(r"(?:(?<=\s)|^)0*(\d{1,4})(?=\s|$)")
_RE_NOISE_TOKEN = re.compile(
    r"(?<![a-z0-9])(?:4k|8k|2160p|1080p|720p|bluray|blu-?ray|bdrip|bd|remux|web-?dl|webrip|web|hdtv|hdr(?:10)?|sdr|hd|hq|dv|x264|x265|h\.?264|h\.?265|hevc|avc|aac|dts|truehd|atmos|flac|ddp?(?:5\.1)?|uhd|60fps|10bit|mp4|mkv)(?![a-z0-9])",
    re.IGNORECASE,
)
_RE_SIZE_TOKEN = re.compile(r"(?<![0-9a-z])\d+(?:\.\d+)?\s*(?:[gmt]i?b|[gmt])(?![a-z0-9])", re.IGNORECASE)
_RE_NOISE_CN = re.compile(
    r"全集|完结|已完结|更新中|持续更新|连载中|未删减|完整版|修复版|典藏版|珍藏版|导演剪辑版|合集|高清|超清|蓝光|原盘|杜比视界|杜比全景声|杜比|国语|粤语|中字|双语|内封字幕|内嵌字幕|外挂字幕|字幕|无水印|独家|首发|附|资源|已刮削|刮削|高码率?|高帧率?|无广告|防和谐|防封|所有季|全季|臻彩MAX\+?|臻彩|原声|国配|剧情|爱情|古装|现代|悬疑|喜剧"
)
_RE_FPS_TOKEN = re.compile(r"(?<![0-9a-z])\d{2,3}\s*(?:fps|帧)(?![a-z0-9])", re.IGNORECASE)
_RE_LONE_STOPWORD = re.compile(r"(?:(?<=\s)|^)(?:无|完|终|版|全|集)(?=\s|$)")
_RE_BRACKET_CONTENT = re.compile(r"[\(\[（【].*?[\)\]）】]")
_RE_PUNCT = re.compile(r"[:：\-_.,·，、!！?？~《》\"'“”]+")
_RE_SPACES = re.compile(r"\s+")
_RE_NON_WORD = re.compile(r"[\s\W_]+", re.UNICODE)
_RE_TRAILING_SEASON_DIGIT = re.compile(r"^(.{2,}?[\u4e00-\u9fff])0*([2-9])$")
_RE_ASCII_ARTICLE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)

_TITLE_SEGMENT_SEPARATORS = ("|", "｜", "/", "／")

_CN_DIGIT = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


@dataclass(slots=True, frozen=True)
class ParsedTitle:
    subjects: tuple[str, ...]
    season: int | None
    episode: int | None


def _cn_numeral_to_int(text: str) -> int | None:
    value = str(text or "").strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if "十" in value:
        head, _, tail = value.partition("十")
        tens = _CN_DIGIT.get(head, 1) if head else 1
        units = _CN_DIGIT.get(tail, 0) if tail else 0
        return tens * 10 + units
    if len(value) == 1:
        return _CN_DIGIT.get(value)
    return None


def _normalize_compact(value: str) -> str:
    return _RE_NON_WORD.sub("", unicodedata.normalize("NFKC", str(value or ""))).lower()


def _normalize_ascii_words(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    return _RE_ASCII_ARTICLE.sub("", text).strip()


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _strip_emoji(text: str) -> str:
    try:
        import emoji as _emoji  # type: ignore

        return _emoji.replace_emoji(text, replace=" ")
    except Exception:
        return _RE_EMOJI.sub(" ", text)


def _pick_season(text: str) -> tuple[int | None, str]:
    if match := _RE_SEASON_CN.search(text):
        season = _cn_numeral_to_int(match.group(1))
        return season, _RE_SEASON_CN.sub(" ", text)
    if match := _RE_SEASON_EN.search(text):
        return int(match.group(1)), _RE_SEASON_EN.sub(" ", text)
    if match := _RE_SEASON_S.search(text):
        return int(match.group(1)), _RE_SEASON_S.sub(" ", text)
    return None, text


def _pick_episode(text: str) -> tuple[int | None, str]:
    if match := _RE_EPISODE_RANGE_CN.search(text):
        number = match.group(1) or match.group(2)
        return int(number), _RE_EPISODE_RANGE_CN.sub(" ", text)
    if match := _RE_EPISODE_TOTAL_CN.search(text):
        number = match.group(1) or match.group(2)
        return int(number), _RE_EPISODE_TOTAL_CN.sub(" ", text)
    if match := _RE_EPISODE_ONLY.search(text):
        return int(match.group(1)), _RE_EPISODE_ONLY.sub(" ", text)
    if match := _RE_EPISODE_BARE_CN.search(text):
        return int(match.group(1)), _RE_EPISODE_BARE_CN.sub(" ", text)
    return None, text


@lru_cache(maxsize=2048)
def parse_title(value: str) -> ParsedTitle:
    """解析标题为「剧名主体变体 + 季号 + 集数」。"""
    text = str(value or "").strip()
    if not text:
        return ParsedTitle(subjects=(), season=None, episode=None)
    text = unicodedata.normalize("NFKC", text)
    # 搜索源标题常带 HTML 实体（如 &amp; 、&nbsp;），先还原避免污染主体
    text = html.unescape(text)
    text = _strip_emoji(text)
    text = re.sub(r"^[\s\W_]+", "", text)
    text = _RE_SOURCE_PREFIX.sub("", text)
    # "名称：xxx" 这类标签可能出现在剔除前缀后（如"#剧集名称："），全文清理
    text = _RE_NAME_LABEL.sub(" ", text)
    text = re.sub(r"^[\s\W_]+", "", text)
    text = _RE_YEAR_BRACKETS.sub(" ", text)

    season: int | None = None
    episode: int | None = None
    # SxxExx - Exx 区间形式先行，取区间上限为当前进度
    if match := _RE_EPISODE_SE_RANGE.search(text):
        season, episode = int(match.group(1)), int(match.group(2))
        text = _RE_EPISODE_SE_RANGE.sub(" ", text)
    if episode is None and (match := _RE_SEASON_EPISODE.search(text)):
        season, episode = int(match.group(1)), int(match.group(2))
        text = _RE_SEASON_EPISODE.sub(" ", text)
    picked_season, text = _pick_season(text)
    if picked_season is not None:
        season = season if season is not None else picked_season
    picked_episode, text = _pick_episode(text)
    if picked_episode is not None:
        episode = episode if episode is not None else picked_episode

    text = _RE_NOISE_TOKEN.sub(" ", text)
    text = _RE_FPS_TOKEN.sub(" ", text)
    text = _RE_SIZE_TOKEN.sub(" ", text)
    text = _RE_BRACKET_CONTENT.sub(" ", text)
    text = _RE_NOISE_CN.sub(" ", text)
    text = _RE_YEAR_BARE.sub(" ", text)
    text = _RE_PUNCT.sub(" ", text)
    text = _RE_LONE_STOPWORD.sub(" ", text)
    text = _RE_SPACES.sub(" ", text).strip()

    # 兼容裸集数 token（如"凡人修仙传 171"）：仅当剔除后主体仍含实词时才采纳
    if episode is None and (match := _RE_EPISODE_BARE_NUM.search(text)):
        remaining = _RE_SPACES.sub(" ", text[: match.start()] + " " + text[match.end() :]).strip()
        if re.search(r"[A-Za-z\u4e00-\u9fff]", remaining):
            episode = int(match.group(1))
            text = remaining

    variants = [text] if text else []
    for separator in _TITLE_SEGMENT_SEPARATORS:
        if text and separator in text:
            variants.extend(part.strip() for part in text.split(separator) if part.strip())
    # 尾部小数字视为季号风格（如"庆余年2"），补充剥离后的变体
    stripped_variants: list[str] = []
    for variant in variants:
        compact = _normalize_compact(variant)
        if match := _RE_TRAILING_SEASON_DIGIT.match(compact):
            stripped_variants.append(match.group(1))
            if season is None:
                season = int(match.group(2))
    variants.extend(stripped_variants)
    subjects = tuple(_dedupe_preserve_order(variants)) or ((str(value or "").strip(),) if str(value or "").strip() else ())
    return ParsedTitle(subjects=subjects, season=season, episode=episode)


def extract_progress(value: str) -> tuple[int | None, int | None]:
    """从标题提取（季, 集）进度，无法识别时对应位置返回 None。"""
    parsed = parse_title(str(value or ""))
    return parsed.season, parsed.episode


def _bigram_jaccard(a: str, b: str) -> float:
    set_a = {a[i : i + 2] for i in range(len(a) - 1)} if len(a) > 1 else {a}
    set_b = {b[i : i + 2] for i in range(len(b) - 1)} if len(b) > 1 else {b}
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def _pair_score(subject: str, name: str) -> float:
    if not subject or not name:
        return 0.0
    if subject == name:
        return 1.0
    shorter, longer = (subject, name) if len(subject) <= len(name) else (name, subject)
    if shorter in longer:
        # 重复堆叠的剧名（如"凡人修仙传 凡人修仙传"）先整体消除再看残差
        residual = longer.replace(shorter, "")
        if not residual:
            return 0.95
        if residual.isdigit() and len(residual) <= 2:
            # 尾部小数字视为季号风格（如"庆余年2" vs "庆余年"）
            return 0.9
        # 防串剧：残差含其他实词（如"许我耀眼" vs "耀眼"）直接否决
        return 0.0
    return max(SequenceMatcher(None, subject, name).ratio(), _bigram_jaccard(subject, name))


def _compare_keys(values: tuple[str, ...]) -> set[str]:
    keys: set[str] = set()
    for value in values:
        compact = _normalize_compact(value)
        if compact:
            keys.add(compact)
        ascii_words = _normalize_ascii_words(value)
        if ascii_words:
            keys.add(_RE_NON_WORD.sub("", ascii_words))
    return keys


@lru_cache(maxsize=512)
def _name_compare_keys(name: str) -> frozenset[str]:
    parsed = parse_title(name)
    subjects = parsed.subjects or ((name.strip(),) if name.strip() else ())
    return frozenset(_compare_keys(subjects))


def title_match_score(title: str, names: tuple[str, ...] | list[str]) -> float:
    """计算标题与任一名称的最高匹配分（0.0~1.0）。"""
    parsed = parse_title(str(title or ""))
    title_keys = _compare_keys(parsed.subjects)
    if not title_keys:
        return 0.0
    best = 0.0
    for raw_name in names or []:
        name = str(raw_name or "").strip()
        if not name:
            continue
        for name_key in _name_compare_keys(name):
            for title_key in title_keys:
                score = _pair_score(title_key, name_key)
                if score > best:
                    best = score
                if best >= 1.0:
                    return best
    return best


def title_matches_names(title: str, names: tuple[str, ...] | list[str], *, threshold: float = DEFAULT_MATCH_THRESHOLD) -> bool:
    """判定标题与任一名称是否同剧。"""
    return title_match_score(title, names) >= threshold

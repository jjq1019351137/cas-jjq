from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter
from typing import Sequence

from app.services.title_match import parse_title

DEFAULT_VECTOR_TOP_K = 8
DEFAULT_VECTOR_MIN_SCORE = 0.05

_RE_TOKEN = re.compile(r"[a-zA-Z]+|\d+|[\u4e00-\u9fff]")
_RE_CJK = re.compile(r"[\u4e00-\u9fff]")
_RE_JOIN_CHAR = re.compile(r"[·・‧•∙]+")
_RE_SEPARATOR = re.compile(r"[^0-9a-z\u4e00-\u9fff]+")


def is_vector_fallback_enabled() -> bool:
    return os.getenv("DRAMA_VECTOR_FALLBACK", "0").strip().lower() in {"1", "true", "yes", "y", "on"}


def _tokenize(text: str) -> list[str]:
    units = _RE_TOKEN.findall(unicodedata.normalize("NFKC", str(text or "")).lower())
    tokens = list(units)
    # 单个汉字信息量低，补相邻汉字 bigram 提升区分度
    for a, b in zip(units, units[1:]):
        if _RE_CJK.fullmatch(a) and _RE_CJK.fullmatch(b):
            tokens.append(a + b)
    return tokens


def _doc_text(title: str) -> str:
    parsed = parse_title(str(title or ""))
    return parsed.subjects[0] if parsed.subjects else str(title or "")


class _TfidfSpace:

    def __init__(self, docs: Sequence[str]) -> None:
        self._n_docs = len(docs)
        self._df: Counter[str] = Counter()
        for doc in docs:
            for term in set(_tokenize(doc)):
                self._df[term] += 1

    def _idf(self, term: str) -> float:
        return math.log((self._n_docs + 1) / (self._df.get(term, 0) + 1)) + 1.0

    def encode(self, text: str) -> dict[str, float]:
        tf = Counter(_tokenize(text))
        if not tf:
            return {}
        max_tf = max(tf.values())
        vec = {term: (0.5 + 0.5 * count / max_tf) * self._idf(term) for term, count in tf.items()}
        norm = math.sqrt(sum(w * w for w in vec.values()))
        if norm <= 0:
            return {}
        return {term: w / norm for term, w in vec.items()}

    @staticmethod
    def similarity(a: dict[str, float], b: dict[str, float]) -> float:
        if not a or not b:
            return 0.0
        if len(a) > len(b):
            a, b = b, a
        return sum(weight * b.get(term, 0.0) for term, weight in a.items())


def _normalized_tokens(value: str) -> list[str]:
    text = unicodedata.normalize("NFKC", str(value or "")).lower()
    text = _RE_JOIN_CHAR.sub("", text)  # 剧名内部间隔号视为连写，如「酱园弄·悬案」
    return [token for token in _RE_SEPARATOR.split(text) if token]


def has_series_conflict(title: str, names: Sequence[str]) -> bool:
    tokens = _normalized_tokens(title)
    if not tokens:
        return True
    for raw_name in names or []:
        name = _RE_SEPARATOR.sub("", _RE_JOIN_CHAR.sub("", unicodedata.normalize("NFKC", str(raw_name or "")).lower()))
        if not name:
            continue
        for token in tokens:
            start = token.find(name)
            while start >= 0:
                before = token[start - 1] if start > 0 else ""
                after_index = start + len(name)
                after = token[after_index] if after_index < len(token) else ""
                # 剧名在本 token 内前后邻居都不是汉字 → 是独立剧名，不算串剧
                if not _RE_CJK.fullmatch(before or " ") and not _RE_CJK.fullmatch(after or " "):
                    return False
                start = token.find(name, start + 1)
    return True


def vector_recall(
    titles: Sequence[str],
    names: Sequence[str],
    *,
    top_k: int = DEFAULT_VECTOR_TOP_K,
    min_score: float = DEFAULT_VECTOR_MIN_SCORE,
) -> list[tuple[int, float]]:
    query = " ".join(str(x or "").strip() for x in (names or []) if str(x or "").strip())
    if not query or not titles:
        return []
    docs = [_doc_text(x) for x in titles]
    space = _TfidfSpace(docs)
    query_vec = space.encode(query)
    if not query_vec:
        return []
    scored: list[tuple[int, float]] = []
    for index, doc in enumerate(docs):
        score = space.similarity(query_vec, space.encode(doc))
        if score < min_score:
            continue
        if has_series_conflict(titles[index], names):
            continue
        scored.append((index, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[: max(int(top_k), 1)]

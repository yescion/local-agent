"""SQLite FTS5 query helpers."""

from __future__ import annotations

import re

FTS5_TOKENIZE = "trigram"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_CJK_RUN_RE = re.compile(r"^[\u4e00-\u9fff]+$")
_TERM_CHUNK_RE = re.compile(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+")


def prepare_fts5_query(raw: str) -> str | None:
    """Turn free-text input into a safe FTS5 MATCH expression.

    Whitespace-delimited tokens are quoted so FTS operators and stray
    punctuation cannot break the MATCH parser. With the trigram tokenizer
    each token is matched as a substring.
    """
    tokens = (raw or "").split()
    if not tokens:
        return None
    return " ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


def like_terms(raw: str) -> list[str] | None:
    """Split a query into AND-ed LIKE terms.

    Whitespace separates terms. A single mixed token is split into digit/Latin
    runs and individual CJK characters so non-adjacent text (e.g.
    ``5分钟…缠论``) can still match.
    """
    q = (raw or "").strip()
    if not q:
        return None
    tokens = q.split()
    if len(tokens) > 1:
        return tokens

    parts: list[str] = []
    for match in _TERM_CHUNK_RE.finditer(tokens[0]):
        chunk = match.group()
        if len(chunk) == 1 or not _CJK_RUN_RE.fullmatch(chunk):
            parts.append(chunk)
        else:
            parts.extend(chunk)
    return parts or None


def should_try_like_fallback(raw: str, fts_hit_count: int) -> bool:
    """Use substring LIKE when trigram FTS misses or the query is very short."""
    q = (raw or "").strip()
    if not q:
        return False
    if fts_hit_count > 0:
        return False
    if len(q) < 3:
        return True
    return bool(_CJK_RE.search(q))

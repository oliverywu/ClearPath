"""Simple, dependency-free passage retrieval over regulations.json.

No embeddings or vector DB -- a deterministic keyword-overlap score keeps
this easy to unit test and reason about, which matters more for a v1 than
retrieval sophistication.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from models import Regulation, JURISDICTIONS

REGULATIONS_PATH = Path(__file__).parent / "regulations.json"

_WORD_RE = re.compile(r"[a-zA-Z0-9]+")

# Common English words that shouldn't drive relevance scoring.
_STOPWORDS = {
    "a", "an", "the", "of", "on", "in", "to", "for", "and", "or", "is", "are",
    "be", "what", "which", "how", "does", "do", "with", "that", "this", "it",
    "must", "shall", "any", "all", "as", "by", "at", "from", "about",
}


def _tokenize(text: str) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text) if w.lower() not in _STOPWORDS}


def load_regulations(path: Path = REGULATIONS_PATH) -> list[Regulation]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Regulation.from_dict(d) for d in raw]


def _score(query_tokens: set[str], reg: Regulation) -> int:
    haystack = " ".join(
        filter(None, [reg.text, reg.title, reg.topic, reg.article])
    )
    reg_tokens = _tokenize(haystack)
    return len(query_tokens & reg_tokens)


def search(
    query: str,
    regulations: Optional[list[Regulation]] = None,
    jurisdiction: Optional[str] = None,
    top_k: int = 5,
) -> list[Regulation]:
    """Return up to `top_k` regulations most relevant to `query`.

    If `jurisdiction` is given, only regulations from that jurisdiction are
    considered. Results with a zero keyword-overlap score are dropped --
    callers should treat an empty result as "nothing found", not retry with
    a looser query, so the chatbot can honestly say nothing matched.
    """
    if regulations is None:
        regulations = load_regulations()

    if jurisdiction is not None:
        if jurisdiction not in JURISDICTIONS:
            raise ValueError(f"Unknown jurisdiction: {jurisdiction!r}")
        regulations = [r for r in regulations if r.jurisdiction == jurisdiction]

    query_tokens = _tokenize(query)
    scored = [(_score(query_tokens, r), r) for r in regulations]
    scored = [(s, r) for s, r in scored if s > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)

    return [r for _, r in scored[:top_k]]


def search_all_jurisdictions(
    query: str,
    regulations: Optional[list[Regulation]] = None,
    top_k_per_jurisdiction: int = 3,
) -> dict[str, list[Regulation]]:
    """Run `search` independently per jurisdiction.

    Returns a dict keyed by every jurisdiction in JURISDICTIONS, including
    ones with an empty list -- so callers can distinguish "no match" from
    "jurisdiction not considered".
    """
    if regulations is None:
        regulations = load_regulations()

    return {
        jurisdiction: search(query, regulations, jurisdiction=jurisdiction, top_k=top_k_per_jurisdiction)
        for jurisdiction in JURISDICTIONS
    }

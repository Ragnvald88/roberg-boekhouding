"""Pure helpers for the Kosten page — no DB, no NiceGUI imports.

Keep this file IO-free so it stays trivially unit-testable.
"""
import re
from pathlib import Path


def derive_status(row: dict) -> str:
    """Return one of: 'hidden' | 'ongecategoriseerd' | 'ontbreekt' | 'compleet'.

    Sequential and mutually exclusive. See spec §5.
    """
    if row.get("id_bank") is not None and row.get("genegeerd"):
        return "hidden"
    if row.get("id_uitgave") is None:
        # bank-tx without a linked uitgave (can't happen for manual rows since
        # id_uitgave is always set there; the None case is bank-only)
        return "ongecategoriseerd"
    if not (row.get("categorie") or "").strip():
        return "ongecategoriseerd"
    if not (row.get("pdf_pad") or "").strip():
        return "ontbreekt"
    return "compleet"


_WORD_RE = re.compile(r"[A-Za-z0-9]+")


def _normalize_tokens(s: str) -> set[str]:
    """Lowercase tokens of length >= 3, alphanumeric only."""
    return {m.group(0).lower() for m in _WORD_RE.finditer(s or "")
            if len(m.group(0)) >= 3}


def match_tokens(tegenpartij: str, filename_stem: str) -> int:
    """Return the number of shared tokens (len >= 3) between the two strings.

    Case-insensitive. Punctuation, whitespace, underscores, hyphens are split.
    Short tokens (< 3 chars, e.g. 'BV', 'NL') are ignored to avoid noise.
    """
    a = _normalize_tokens(tegenpartij)
    b = _normalize_tokens(Path(filename_stem).stem)
    return len(a & b)


def tegenpartij_color(s: str) -> str:
    """Deterministic HSL color from a string (mirrors the HTML mockup helper)."""
    h = 0
    for c in s or "":
        h = (h * 31 + ord(c)) % 360
    return f"hsl({h} 55% 48%)"


def initials(s: str) -> str:
    """First letters of the first two alphanumeric tokens.

    For a single-token input, returns the first two characters of that token.
    Returns '?' for empty input. Uppercases.
    """
    tokens = _WORD_RE.findall(s or "")
    if not tokens:
        return "?"
    if len(tokens) == 1:
        return tokens[0][:2].upper()
    return "".join(t[0] for t in tokens[:2]).upper()

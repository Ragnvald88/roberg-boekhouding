"""Pure helpers for the Transacties page — no DB, no NiceGUI imports.

Keep this file IO-free so it stays trivially unit-testable.
"""
import re
from pathlib import Path


def derive_status(row: dict) -> str:
    """Sign-aware, priority-ordered status. See spec §4.1 steps 1-8.

    Returns one of:
      'prive_verborgen' | 'gekoppeld_factuur' | 'ongecategoriseerd' |
      'ontbreekt_bon' | 'compleet' | 'gecategoriseerd'

    Sequential and mutually exclusive.
    """
    if row.get("id_bank") is not None and row.get("genegeerd"):
        return "prive_verborgen"
    if (row.get("koppeling_type") == "factuur"
            and row.get("id_bank") is not None):
        return "gekoppeld_factuur"

    bedrag = row.get("bedrag") or 0.0
    cat = (row.get("categorie") or "").strip()
    pdf = (row.get("pdf_pad") or "").strip()

    if bedrag < 0:
        if row.get("id_uitgave") is None:
            return "ongecategoriseerd"
        if not cat:
            return "ongecategoriseerd"
        if not pdf:
            return "ontbreekt_bon"
        return "compleet"
    else:
        # Positive / income-side (no bon-concept for positives).
        if not cat:
            return "ongecategoriseerd"
        return "gecategoriseerd"


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

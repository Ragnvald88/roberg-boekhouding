"""Klant name resolution for invoice import.

Resolves a PDF-extracted klant name and/or filename suffix to a klant_id
via the `klant_aliases` DB table (no module-level state).

Strategy order (resolve_klant):
  1. Exact suffix match (filename_suffix → type='suffix')
  2. Exact pdf_text match (pdf_name → type='pdf_text')
  3. Direct klanten.naam match (case-insensitive)
  4. Fuzzy bidirectional substring (length(pattern) >= 3, longest pattern wins)

For ANW filenames: pattern-substring-of-filename match, case-insensitive,
longest pattern wins.
"""

from __future__ import annotations
from pathlib import Path
import aiosqlite
from database import DB_PATH, get_db_ctx


async def _query_one(db_path: Path, sql: str,
                      params: tuple) -> tuple[str, int] | None:
    """Run sql, return (naam, id) of first row or None. Uses Row factory."""
    async with get_db_ctx(db_path) as conn:
        prev_factory = conn.row_factory
        conn.row_factory = aiosqlite.Row
        try:
            cur = await conn.execute(sql, params)
            row = await cur.fetchone()
        finally:
            conn.row_factory = prev_factory
    if row is None:
        return None
    return row['naam'], row['id']


async def resolve_klant(db_path: Path = DB_PATH,
                        pdf_name: str | None = None,
                        filename_suffix: str | None = None
                        ) -> tuple[str | None, int | None]:
    """Resolve klant by PDF text and/or filename suffix.

    Returns (klant_naam, klant_id) or (None, None) if no match.
    """
    if filename_suffix:
        match = await _query_one(db_path, """
            SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
            JOIN klanten k ON k.id = a.klant_id
            WHERE a.type = 'suffix' AND a.pattern = ?
            LIMIT 1
        """, (filename_suffix.strip(),))
        if match:
            return match

    if pdf_name:
        match = await _query_one(db_path, """
            SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
            JOIN klanten k ON k.id = a.klant_id
            WHERE a.type = 'pdf_text' AND a.pattern = ?
            LIMIT 1
        """, (pdf_name.strip(),))
        if match:
            return match

        match = await _query_one(db_path, """
            SELECT id, naam FROM klanten
            WHERE naam = ? COLLATE NOCASE
            ORDER BY id ASC
            LIMIT 1
        """, (pdf_name.strip(),))
        if match:
            return match

        match = await _query_one(db_path, """
            SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
            JOIN klanten k ON k.id = a.klant_id
            WHERE a.type = 'pdf_text'
              AND length(a.pattern) >= 3
              AND (instr(LOWER(?), LOWER(a.pattern)) > 0
                OR instr(LOWER(a.pattern), LOWER(?)) > 0)
            ORDER BY length(a.pattern) DESC, k.id ASC
            LIMIT 1
        """, (pdf_name.strip(), pdf_name.strip()))
        if match:
            return match

    return None, None


async def resolve_anw_klant(db_path: Path = DB_PATH,
                             filename: str = ''
                             ) -> tuple[str | None, int | None]:
    """Resolve ANW klant from filename via klant_aliases (type='anw_filename').

    Pattern is a substring of filename, case-insensitive. Longest pattern wins,
    then ASC klant_id for determinism. Returns (klant_naam, klant_id) or
    (None, None).
    """
    if not filename:
        return None, None
    match = await _query_one(db_path, """
        SELECT k.naam AS naam, k.id AS id FROM klant_aliases a
        JOIN klanten k ON k.id = a.klant_id
        WHERE a.type = 'anw_filename'
          AND length(a.pattern) >= 3
          AND instr(LOWER(?), LOWER(a.pattern)) > 0
        ORDER BY length(a.pattern) DESC, k.id ASC
        LIMIT 1
    """, (filename.strip(),))
    return match if match else (None, None)

"""Documentation discipline tests for CLAUDE.md / AGENTS.md.

Per Anthropic best-practice 2026: bloated CLAUDE.md gets ignored
("instructions get lost in the noise"). Per OpenAI Codex: 32 KiB
default `project_doc_max_bytes` cap silently truncates AGENTS.md.

These tests enforce the structural invariants of the doc layer:
- Line + byte budgets (under both Anthropic + Codex thresholds)
- No duplicate H3 sections (catches botched cleanups like c905bd0)
- No "Sprint X state" headings (CLAUDE.md = current state, not log)
- No stale `baseline NNNN` strings (test count drifts each sprint)
- Architecture pointers exist (slim CLAUDE.md must point to docs/)
- AGENTS.md and CLAUDE.md share core content (symlink or sync)

If you need to bend a budget temporarily, raise the threshold here
with a comment explaining why — don't silently let it grow.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.parent
CLAUDE_MD = ROOT / 'CLAUDE.md'
AGENTS_MD = ROOT / 'AGENTS.md'
ARCH_DIR = ROOT / 'docs' / 'architecture'

# Thresholds
MAX_LINES = 200          # Anthropic: bloated files get ignored after ~200
MAX_BYTES = 30_000       # Codex default `project_doc_max_bytes` = 32 KiB
                         # 30 KiB leaves margin without bumping config


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _line_count(path: Path) -> int:
    # Match `wc -l` semantics (counts newlines)
    return _read(path).count('\n')


# ---------------------------------------------------------------------------
# Size budgets
# ---------------------------------------------------------------------------

def test_claude_md_under_line_budget():
    """Anthropic 2026: long CLAUDE.md = ignored CLAUDE.md."""
    lines = _line_count(CLAUDE_MD)
    assert lines <= MAX_LINES, (
        f"CLAUDE.md is {lines} lines, over the {MAX_LINES}-line budget. "
        f"Move detail to docs/architecture/*.md and link from here."
    )


def test_claude_md_under_byte_budget():
    """Codex `project_doc_max_bytes` default is 32 KiB. Stay under 30 KiB
    so we don't risk silent truncation in codex-review runs."""
    size = os.path.getsize(CLAUDE_MD)
    assert size <= MAX_BYTES, (
        f"CLAUDE.md is {size} bytes, over the {MAX_BYTES}-byte budget. "
        f"Codex would silently truncate the tail. "
        f"Move detail to docs/architecture/*.md."
    )


def test_agents_md_size_matches_claude_md():
    """AGENTS.md must follow the same budget — Codex reads it too.
    Whether symlink or copy, size constraint applies equally."""
    assert AGENTS_MD.exists() or AGENTS_MD.is_symlink(), (
        "AGENTS.md missing — Codex/Cursor/etc. won't see project context"
    )
    size = os.path.getsize(AGENTS_MD)
    assert size <= MAX_BYTES, f"AGENTS.md is {size} bytes, over budget"


# ---------------------------------------------------------------------------
# Structural invariants
# ---------------------------------------------------------------------------

def test_no_duplicate_h2_or_h3_headings():
    """Catches botched cleanups like c905bd0 (which left two
    `### VA-tracker drill-down (Sprint J)` blocks in CLAUDE.md)."""
    headings = re.findall(r'^#{2,3} .+$', _read(CLAUDE_MD), re.MULTILINE)
    counts = Counter(headings)
    dups = {h: n for h, n in counts.items() if n > 1}
    assert not dups, (
        f"Duplicate headings in CLAUDE.md: {dups}. "
        f"Likely a botched merge or partial dedup."
    )


def test_no_sprint_state_headings():
    """CLAUDE.md describes current operating constraints, not chronology.
    Sprint state belongs in git log + docs/superpowers/specs/.

    Block ALL `## Sprint X` / `### Sprint X` headings — even ones not
    explicitly labelled state/recap (e.g. `### Sprint I — VA-tracker
    basis` would otherwise sneak through). Inline body refs like
    'Sprint A pattern' in prose are fine."""
    text = _read(CLAUDE_MD)
    bad = re.findall(
        r'^#{2,4} .*\bSprint [A-Z]\b.*$', text, re.MULTILINE,
    )
    assert not bad, (
        f"Sprint headings in CLAUDE.md: {bad}. "
        f"Move recap to docs/superpowers/specs/ + git log; "
        f"CLAUDE.md is current state only."
    )


def test_no_stale_test_baselines():
    """Specific 'baseline 1298', 'baseline 1386' etc. strings rot fast.
    Don't pin them in CLAUDE.md — pytest gives the live count."""
    text = _read(CLAUDE_MD)
    matches = re.findall(r'baseline\s+\d{3,5}', text, re.IGNORECASE)
    assert not matches, (
        f"Stale baseline counts in CLAUDE.md: {matches}. "
        f"Remove — let pytest report the current count."
    )


def test_architecture_pointers_exist():
    """The slim CLAUDE.md must point to docs/architecture/ for deep
    detail. Each pointer file must actually exist."""
    text = _read(CLAUDE_MD)
    refs = re.findall(r'docs/architecture/([\w-]+\.md)', text)
    assert refs, (
        "CLAUDE.md has no docs/architecture/*.md pointers. "
        "If detail moved out, the pointers must lead readers to it."
    )
    missing = [r for r in refs if not (ARCH_DIR / r).exists()]
    assert not missing, (
        f"CLAUDE.md points to non-existent architecture docs: {missing}"
    )


def test_agents_md_shares_core_with_claude_md():
    """AGENTS.md (Codex/Cursor/etc.) must share the same core as CLAUDE.md
    (Claude). Symlink is the simplest way; near-copy is acceptable as
    long as the project intro + top gotchas + commands match.

    We assert both files contain the same architecture-pointer table —
    that proves they describe the same project, even if AGENTS.md is
    a near-copy without Claude-specific @-imports."""
    claude_text = _read(CLAUDE_MD)
    agents_text = _read(AGENTS_MD)

    # If symlinked, they're identical — done.
    if AGENTS_MD.is_symlink():
        assert claude_text == agents_text
        return

    # If separate files, both must contain the architecture-pointer
    # section and the top-gotcha section.
    for marker in ('## Architecture deep-dive', '## Top gotchas'):
        assert marker in claude_text, f"CLAUDE.md missing '{marker}'"
        assert marker in agents_text, (
            f"AGENTS.md missing '{marker}' — out of sync with CLAUDE.md"
        )


# ---------------------------------------------------------------------------
# Architecture docs
# ---------------------------------------------------------------------------

def test_architecture_docs_under_individual_budget():
    """Each architecture doc should stay focused. Anything > 200 lines
    is a sign it should split further."""
    if not ARCH_DIR.exists():
        return  # Slim refactor not done yet
    over = []
    for md in ARCH_DIR.glob('*.md'):
        n = md.read_text(encoding='utf-8').count('\n')
        if n > 200:
            over.append((md.name, n))
    assert not over, (
        f"Architecture docs over 200 lines (split further?): {over}"
    )


# ---------------------------------------------------------------------------
# Cross-doc reference integrity
# ---------------------------------------------------------------------------

# Files that look like Python module paths in backticks. The pattern
# matches `path/to/file.py` or `path/to/file.py:symbol`. We verify the
# file actually exists.
_PY_REF_RE = re.compile(
    r'`([\w./_-]+\.py)(?::[\w_]+)?`'
)


def _collect_py_refs(text: str) -> set[str]:
    return {m for m in _PY_REF_RE.findall(text)
            # Exclude paths that look like fragments, not real files
            if '/' in m and not m.startswith(('~', '/'))}


def test_architecture_docs_python_refs_resolve():
    """Catch pointer rot in docs/architecture/*.md: backtick-quoted
    Python module paths must point to actual files. Caught in Codex
    review: `invoice_builder.py:genereer_factuur` should have been
    `components/invoice_builder.py:genereer_factuur`."""
    if not ARCH_DIR.exists():
        return
    broken = []
    for md in ARCH_DIR.glob('*.md'):
        refs = _collect_py_refs(md.read_text(encoding='utf-8'))
        for ref in refs:
            if not (ROOT / ref).exists():
                broken.append((md.name, ref))
    assert not broken, (
        f"Broken Python module refs in architecture docs: {broken}. "
        f"Either fix the path or remove the backtick-quote so it reads "
        f"as plain text."
    )


def test_claude_md_python_refs_resolve():
    """Same check for CLAUDE.md root."""
    refs = _collect_py_refs(_read(CLAUDE_MD))
    broken = [r for r in refs if not (ROOT / r).exists()]
    assert not broken, f"Broken Python module refs in CLAUDE.md: {broken}"

#!/bin/bash
# Codex Stop hook: ask Claude to review the diff Codex just produced.
#
# Mirrors `.codex/hooks/quality-gate.sh` shape but inverts the agent
# direction. Closes the cross-vendor review gap: when the user runs
# Codex directly (not via Claude's `codex-review` skill), Claude
# wouldn't otherwise see the diff.
#
# Exit 0 = allow stop, with Claude's review printed as informational
#         message (does NOT block — Claude's review is opinion, not
#         deterministic ground truth like tests).
# Kill switch: SKIP_CLAUDE_REVIEW=1
# Auto-skip: stop_hook_active, no code-file changes, diff < 5 lines,
#            claude CLI not installed.

INPUT=$(cat)

# Prevent infinite loops
if echo "$INPUT" | jq -r '.stop_hook_active' 2>/dev/null | grep -q 'true'; then
  exit 0
fi

# Kill switch (set when running batch ops or when Claude is what
# triggered Codex in the first place — avoid Claude reviewing its own
# subprocess result)
[ "${SKIP_CLAUDE_REVIEW:-0}" = "1" ] && exit 0

# Codex sets CODEX_PROJECT_DIR; fall back to PWD
cd "${CODEX_PROJECT_DIR:-$PWD}" || exit 0

# Only review if code files changed
CHANGED=$(git diff HEAD --name-only 2>/dev/null | grep -E '\.(py|html|sql|css|js)$')
[ -z "$CHANGED" ] && exit 0

# Skip trivial diffs
DIFF=$(git diff HEAD -- '*.py' '*.html' '*.sql' '*.css' '*.js' 2>/dev/null)
LINES=$(printf '%s\n' "$DIFF" | wc -l | tr -d ' ')
[ "$LINES" -lt 5 ] && exit 0

# Bail silently if Claude CLI is not installed (don't block Codex)
if ! command -v claude >/dev/null 2>&1; then
  exit 0
fi

# Run Claude review. Timeout 90s — typical headless review is 30-60s.
REVIEW=$(printf '%s\n' "$DIFF" | timeout 90 claude -p "Review this diff that Codex just produced in the Boekhouding project (NiceGUI/Python/SQLite, eenmanszaak huisartswaarnemer). Read CLAUDE.md root + docs/architecture/*.md for full context.

Flag specifically:
- Bugs, off-by-one, edge cases (date/year-logica, factuur-status, bank-tx)
- SQL-filter consistency: ZICHTBARE_ZAKELIJKE_UITGAVE_FILTER, FACTUREERBARE_WERKDAG_FILTER, status='concept' exclusions, sign conventions
- Year-locking violations: mutaties op definitieve jaren zonder assert_year_writable (zie docs/architecture/year-lock.md)
- PDF path resolution: row-menu actions via _ensure_factuur_pdf (zie docs/architecture/invoices.md)
- NiceGUI patterns: q-btn-dropdown teleport bug, ui.upload await e.file.read(), linear_progress show_value=False
- CSS cascade: Quasar overrides + app-classes-op-Quasar BUITEN @layer components
- Test gaps: did Codex add tests where invariants matter?

Be terse, MAX 6 bullets, file:line waar relevant. Reply exactly 'GEEN BEVINDINGEN' if clean. No 'what does this code do' summaries, no style nits, no speculative refactors." 2>&1)

# Print findings as info (don't block). User reads and decides.
if [ -n "$REVIEW" ] && ! echo "$REVIEW" | grep -q "^GEEN BEVINDINGEN"; then
  echo "" >&2
  echo "=== Claude review of Codex diff ===" >&2
  echo "$REVIEW" >&2
  echo "" >&2
  echo "(Claude's review is opinion — verify before acting. Set SKIP_CLAUDE_REVIEW=1 to disable.)" >&2
fi

exit 0

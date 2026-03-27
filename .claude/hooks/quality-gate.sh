#!/bin/bash
# Stop hook: block Claude from finishing if tests fail.
# Exit 0 = allow stop. Exit 2 = block (stderr injected as user message).

INPUT=$(cat)

# Prevent infinite loops: if stop_hook already fired, allow stop
if echo "$INPUT" | jq -r '.stop_hook_active' 2>/dev/null | grep -q 'true'; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR" || exit 0

# Only run if Python files were likely changed (check git status)
if ! git diff --name-only HEAD 2>/dev/null | grep -qE '\.py$|\.html$'; then
  # No Python/HTML changes — skip test enforcement
  exit 0
fi

# Run tests
export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib
TEST_OUTPUT=$(.venv/bin/python -m pytest tests/ -q --tb=short 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -ne 0 ]; then
  echo "Tests failing. Fix before completing:" >&2
  echo "$TEST_OUTPUT" | tail -15 >&2
  exit 2
fi

exit 0

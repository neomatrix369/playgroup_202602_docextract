#!/usr/bin/env bash
set -euo pipefail

SKILL_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_DOCEXTRACT_ROOT="$(cd "$SKILL_ROOT/../../.." && pwd)"
DEFAULT_PAGES_ROOT="/Users/swami/git-repos/ai-ml-dl-stuff/tools-and-utilities/neomatrix369.github.io"
DOCEXTRACT_ROOT="${DOCEXTRACT_ROOT:-$DEFAULT_DOCEXTRACT_ROOT}"
PAGES_ROOT="${PAGES_ROOT:-$DEFAULT_PAGES_ROOT}"
export DOCEXTRACT_ROOT PAGES_ROOT

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ -d "$DOCEXTRACT_ROOT/.git" ]] || fail "DocExtract repository not found: $DOCEXTRACT_ROOT"
[[ -d "$PAGES_ROOT/.git" ]] || fail "Pages repository not found: $PAGES_ROOT"
[[ -f "$DOCEXTRACT_ROOT/which-models-extracted-playground.html" ]] || fail "source playground missing"
[[ -f "$DOCEXTRACT_ROOT/.claude/skills/docextract-workflow/playground-integrity.md" ]] || fail "integrity checklist missing"

PYTHON3="${DOCEXTRACT_ROOT}/.venv/bin/python3"
[[ -x "$PYTHON3" ]] || PYTHON3="python3"
"$PYTHON3" "$SKILL_ROOT/scripts/sync.py"

echo "Preview: cd \"$PAGES_ROOT\" && python3 -m http.server 8080"
echo "Latest: http://localhost:8080/demos/playgroup-202602-docextract/latest/"

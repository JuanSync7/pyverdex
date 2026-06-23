#!/usr/bin/env bash
# Populate the vendored deterministic tools + knowledge docs that pyverify runs
# against. These are copies of a SEPARATE repo (juansync-synapse) and are
# intentionally NOT committed here — sync them from your own checkout:
#
#   ./scripts/sync-vendor.sh /path/to/juansync-synapse
#   PYVERIFY_JUANSYNC_ROOT=/path/to/juansync-synapse ./scripts/sync-vendor.sh
#
# After syncing, `uv run pytest` and `pyverify run` work against the real tools.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-${PYVERIFY_JUANSYNC_ROOT:-}}"
if [ -z "$SRC" ]; then
  echo "usage: $0 <juansync-synapse-root>   (or set PYVERIFY_JUANSYNC_ROOT)" >&2
  exit 2
fi
# tolerate the doubled-path layout (juansync-synapse/juansync-synapse)
[ -d "$SRC/src/tools/testing" ] || SRC="$SRC/juansync-synapse"
[ -d "$SRC/src/tools/testing" ] || { echo "no src/tools/testing under $SRC" >&2; exit 2; }

DST="$ROOT/src/pyverify"
TOOLS="assertion_quality boundary_classifier branch_mapper coverage_analyzer \
flakiness_checker hypothesis_strategy_generator lint_reporter \
log_contract_validator mutation_runner secret_scanner"
SKILLS="test-lint test-fix test-audit test-generate test-evaluate test-integrate test-runner"

mkdir -p "$DST/tools/vendored" "$DST/knowledge/skills" "$DST/knowledge/protocols" "$DST/knowledge/tools"
: > "$DST/tools/vendored/__init__.py"

for t in $TOOLS; do
  rm -rf "$DST/tools/vendored/$t"
  cp -r "$SRC/src/tools/testing/$t" "$DST/tools/vendored/$t"
  [ -f "$SRC/src/tools/testing/$t/TOOL.md" ] && cp "$SRC/src/tools/testing/$t/TOOL.md" "$DST/knowledge/tools/$t.md"
done
for s in $SKILLS; do
  rm -rf "$DST/knowledge/skills/$s"
  cp -r "$SRC/src/skills/code/$s" "$DST/knowledge/skills/$s"
done
cp "$SRC/src/protocols/delivery/"*.md "$DST/knowledge/protocols/" 2>/dev/null || true
find "$DST/tools/vendored" "$DST/knowledge" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

echo "synced $(echo "$TOOLS" | wc -w) tools + knowledge docs from $SRC"

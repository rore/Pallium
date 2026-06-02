#!/usr/bin/env bash
# scripts/agent-redline-check.sh
#
# Local mirror of the agent-redline CI check.
# Runs the reporter against the local diff (vs. the configured base branch)
# and prints the verdict.
#
# The reporter dispatches on the policy's `boundaryAdapter` block, so this
# script is stack-neutral: a Spring repo's policy declares
# outputFormat: junit-xml + outputPath: build/test-results/...; a Python
# repo's declares outputFormat: json-violations + outputPath:
# build/import-linter-report.json. Either way, this script only needs to
# know where the reporter is.
#
# Usage:
#   ./scripts/agent-redline-check.sh                    # against origin/main
#   ./scripts/agent-redline-check.sh --base develop     # different base
#
# Notes on api.type: openapi-from-controllers
#   The CI workflow generates spec_base.yaml + spec_head.yaml at the two
#   SHAs and passes them to the reporter. This local check does NOT run
#   the generation command (running two builds during a pre-push is
#   hostile). It relies on red-zone path classification — touched
#   controllers are red and trigger api-review via the policy. CI sees
#   the structural diff; the local run sees "you touched a controller."
#   That asymmetry is by design.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BASE_REF="origin/main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base) BASE_REF="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 1 ;;
  esac
done

# The reporter is vendored at scripts/agent-redline-report.py during bootstrap
# (Phase 4). Without it the local check can't run. If you see this error,
# re-run bootstrap or copy the reporter manually from the agent-redline skill
# at .claude/skills/agent-redline/scripts/agent-redline-report.py.
REPORTER_PY="$REPO_ROOT/scripts/agent-redline-report.py"
if [[ ! -f "$REPORTER_PY" ]]; then
  echo "error: reporter not found at $REPORTER_PY" >&2
  echo "       Re-run agent-redline bootstrap or copy the reporter from" >&2
  echo "       .claude/skills/agent-redline/scripts/agent-redline-report.py" >&2
  exit 1
fi

POLICY="$REPO_ROOT/agent-policy.yaml"
if [[ ! -f "$POLICY" ]]; then
  echo "error: $POLICY not found. Run agent-redline bootstrap first." >&2
  exit 1
fi

# Resolve base SHA. If origin isn't fetched, fall back to local main.
if ! BASE_SHA=$(git rev-parse "$BASE_REF" 2>/dev/null); then
  echo "warning: $BASE_REF not found; trying local main" >&2
  BASE_SHA=$(git rev-parse main 2>/dev/null || true)
  if [[ -z "$BASE_SHA" ]]; then
    echo "error: cannot resolve a base ref" >&2
    exit 1
  fi
fi
HEAD_SHA=$(git rev-parse HEAD)

# Compute the changed-files list and total lines changed.
# Empty diffs (BASE == HEAD) produce no shortstat output; the awk pipeline
# would emit nothing without the END block, and `--lines-changed ""` would
# be rejected by argparse `type=int`. END{print s+0} guarantees a numeric
# value; the `:-0` is belt-and-suspenders.
CHANGED_FILES_LIST="$(mktemp)"
trap 'rm -f "$CHANGED_FILES_LIST"' EXIT
git diff --name-only "$BASE_SHA"..."$HEAD_SHA" > "$CHANGED_FILES_LIST"
LINES_CHANGED=$(git diff --shortstat "$BASE_SHA"..."$HEAD_SHA" \
  | awk '{for (i=1;i<=NF;i++) if ($i ~ /insertions?|deletions?/) s+=$(i-1)} END{print s+0}')
LINES_CHANGED=${LINES_CHANGED:-0}

# Optional pre-step: run the Python extension's adapter so the reporter has
# a fresh json-violations report to read. Skipped silently if the adapter
# isn't present (Spring repos rely on `./gradlew test` having been run;
# zone-only repos have no backend and need no pre-step).
if [[ -f "$REPO_ROOT/scripts/run-import-linter.py" ]]; then
  mkdir -p "$REPO_ROOT/build"
  python "$REPO_ROOT/scripts/run-import-linter.py" \
    --out "$REPO_ROOT/build/import-linter-report.json" || true
fi

# The reporter reads policy.boundaryAdapter to know what format to expect
# at outputPath. We don't pass --boundary-report / --boundary-format
# explicitly; the policy is the source of truth.
exec python "$REPORTER_PY" \
  --policy "$POLICY" \
  --changed-files "$CHANGED_FILES_LIST" \
  --lines-changed "$LINES_CHANGED" \
  --default-mode "${MODE:-shadow}"

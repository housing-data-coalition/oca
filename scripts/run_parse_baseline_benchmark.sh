#!/usr/bin/env bash
# Repeatable Task 1 baseline: parse -> DuckDB -> export -> CSV preprocess.
# Writes artifacts to cursor-workspaces (not the oca repo).
set -euo pipefail
ARTIFACTS_DIR="${OCA_BENCHMARK_ARTIFACTS_DIR:-/Users/maxwell/justfix/repos/cursor-workspaces/oca-etl/.cursor/plans/artifacts}"
mkdir -p "$ARTIFACTS_DIR"
cd "$(dirname "$0")/.."
docker compose run --rm \
  -v "${ARTIFACTS_DIR}:/benchmark-artifacts" \
  app python -m lib.etl_benchmark \
  --output-dir /benchmark-artifacts \
  --iterations "${OCA_BENCHMARK_ITERATIONS:-2}" \
  "$@"

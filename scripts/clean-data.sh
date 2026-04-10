#!/usr/bin/env bash
# Remove all Pallium runtime data (SQLite DB + vector index) for a fresh start.
# Usage: bash scripts/clean-data.sh

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

rm -f pallium.db pallium.db.schema.lock pallium.db-wal pallium.db-shm .pallium-schema-init.lock
rm -f pallium_vector.index pallium_vector.index.idmap.json pallium_vector.index.meta.json
rm -f tmp*.db tmp*.db.schema.lock tmp-*.db tmp-*.db.schema.lock test_tmp.db test_tmp.db.schema.lock

echo "Cleaned: SQLite DB, vector index, and temp files."

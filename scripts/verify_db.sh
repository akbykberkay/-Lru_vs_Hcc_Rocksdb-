#!/usr/bin/env bash
# Verify the loaded DB in $DB_DIR (see analysis/verify_db.py for the checks).
set -euo pipefail
source "$(dirname "$0")/../config/common.sh"
python3 "$PROJ/analysis/verify_db.py" "$DB_DIR" "$SST_DUMP" "$RESULTS/load/load.log" \
  "$RESULTS/load" "$NUM_KEYS"

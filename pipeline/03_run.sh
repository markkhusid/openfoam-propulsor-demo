#!/usr/bin/env bash
# Run transient foamRun in parallel with optional disk watchdog.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

load_config "${1:-}"
preset_defaults
[[ -d "${CASE_DIR:-}" ]] || die "CASE_DIR missing"

if [[ ! -d "$CASE_DIR/processor0/constant/polyMesh" && ! -d "$CASE_DIR/constant/polyMesh" ]]; then
  warn "No mesh found — running 02_mesh.sh first"
  "$DIR/02_mesh.sh" "${PIPELINE_CONFIG}"
fi

MAX_GB="${MAX_CASE_GB:-50}"
info "Solving $CASE_DIR  (disk budget ${MAX_GB} GB)"

# Disk watchdog
(
  while true; do
    sleep 60
    [[ -d "$CASE_DIR" ]] || exit 0
    sz=$(bytes_of "$CASE_DIR")
    free=$(df -B1 "$CASE_DIR" | awk 'NR==2{print $4}')
    python3 - "$sz" "$free" "$MAX_GB" <<'PY' || exit 0
import sys
sz, free, max_gb = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
if sz > max_gb * 1e9 or free < 2e9:
    sys.exit(1)
sys.exit(0)
PY
    if [[ $? -ne 0 ]]; then
      warn "Disk limit hit (case or free space) — signalling solvers"
      # Best-effort: stop foamRun containers/processes for this user
      pkill -f 'foamRun -parallel' 2>/dev/null || true
      exit 0
    fi
  done
) &
WATCH=$!
trap 'kill $WATCH 2>/dev/null || true' EXIT

of_run '
  set -e
  # Fresh fields on processors; keep mesh
  for d in processor*; do
    [ -d "$d" ] || continue
    find "$d" -maxdepth 1 -mindepth 1 ! -name constant -exec rm -rf {} +
  done
  decomposePar -fields -copyZero 2>&1 | tee log.decomposePar_fields
  mpirun --oversubscribe -np '"${NPROCS}"' foamRun -parallel 2>&1 | tee log.foamRun
  reconstructPar -latestTime 2>&1 | tee log.reconstructPar || true
'

kill $WATCH 2>/dev/null || true
info "Solve finished. Forces: $CASE_DIR/postProcessing/forces"
info "Next: $DIR/04_movie.sh  and/or  $DIR/05_efficiency.sh"

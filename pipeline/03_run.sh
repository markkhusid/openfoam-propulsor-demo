#!/usr/bin/env bash
# Run foamRun (serial or parallel) with optional disk watchdog.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

load_config "${1:-}"
preset_defaults
[[ -d "${CASE_DIR:-}" ]] || die "CASE_DIR missing"

mode="${ROTATION_MODE:-mrf}"
nprocs="${NPROCS:-4}"

if [[ ! -d "$CASE_DIR/constant/polyMesh" && ! -d "$CASE_DIR/processor0/constant/polyMesh" ]]; then
  warn "No mesh found — running 02_mesh.sh first"
  "$DIR/02_mesh.sh" "${PIPELINE_CONFIG}"
fi

MAX_GB="${MAX_CASE_GB:-50}"
info "Solving $CASE_DIR  mode=${mode}  nprocs=${nprocs}  disk budget ${MAX_GB} GB"

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
      warn "Disk limit hit — signalling foamRun"
      # avoid self-matching kill patterns: target docker/openfoam only
      docker ps -q --filter ancestor="${OF_IMAGE:-openfoam/openfoam11-paraview510:latest}" | xargs -r docker kill 2>/dev/null || true
      exit 0
    fi
  done
) &
WATCH=$!
trap 'kill $WATCH 2>/dev/null || true' EXIT

if [[ "$nprocs" -le 1 ]]; then
  of_run '
    set -e
    # Ensure MRF zone if needed
    if [ -f system/topoSetDict ]; then
      topoSet 2>&1 | tee log.topoSet_run || true
    fi
    # Clean prior time directories except 0
    find . -maxdepth 1 -type d \( -name "[1-9]*" -o -name "0.*" \) -exec rm -rf {} + 2>/dev/null || true
    foamRun 2>&1 | tee log.foamRun
  '
else
  of_run '
    set -e
    if [ -f system/topoSetDict ] && [ -d constant/polyMesh ]; then
      topoSet 2>&1 | tee log.topoSet_run || true
    fi
    # Fresh fields on processors; keep mesh
    for d in processor*; do
      [ -d "$d" ] || continue
      find "$d" -maxdepth 1 -mindepth 1 ! -name constant -exec rm -rf {} +
    done
    if [ ! -d processor0 ]; then
      decomposePar -force -noFields 2>&1 | tee log.decomposePar
    fi
    decomposePar -fields -copyZero 2>&1 | tee log.decomposePar_fields
    mpirun --oversubscribe -np '"${nprocs}"' foamRun -parallel 2>&1 | tee log.foamRun
    reconstructPar -latestTime 2>&1 | tee log.reconstructPar || true
  '
fi

kill $WATCH 2>/dev/null || true
info "Solve finished. Forces: $CASE_DIR/postProcessing/forces"
info "Next: $DIR/04_movie.sh  and/or  $DIR/05_efficiency.sh"

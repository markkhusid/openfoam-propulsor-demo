#!/usr/bin/env bash
# Generate mesh (MRF: NPROCS parallel snappy + topoSet; sliding: parallel snappy + NCC).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

load_config "${1:-}"
preset_defaults
[[ -d "${CASE_DIR:-}" ]] || die "CASE_DIR missing — run 01_prepare_case.sh first"
[[ -f "$CASE_DIR/Allmesh" ]] || die "No Allmesh in $CASE_DIR — run 01_prepare_case.sh"

mode="${ROTATION_MODE:-mrf}"
info "Meshing $CASE_DIR  mode=${mode}  nprocs=${NPROCS}  preset=${MESH_PRESET}"
of_run 'chmod +x Allmesh Allrun Allclean 2>/dev/null; ./Allmesh'

# Sanity: MRF needs cellZone rotatingZone
if [[ "$mode" == "mrf" ]]; then
  of_run 'foamDictionary constant/polyMesh/cellZones 2>/dev/null | head -5 || true'
  if ! of_run 'test -f constant/polyMesh/cellZones && ! grep -q "0 // entry0" constant/polyMesh/cellZones 2>/dev/null'; then
    # binary cellZones hard to grep — just run topoSet again
    of_run 'topoSet 2>&1 | tail -15' || warn "topoSet re-run failed — check log.topoSet"
  fi
fi

info "Mesh complete. Logs: log.snappyHexMesh, log.blockMesh, log.topoSet (MRF)"
info "Next: $DIR/03_run.sh"

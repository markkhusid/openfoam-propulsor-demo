#!/usr/bin/env bash
# Generate mesh (blockMesh + snappyHexMesh + sliding interface).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

load_config "${1:-}"
preset_defaults
[[ -d "${CASE_DIR:-}" ]] || die "CASE_DIR missing — run 01_prepare_case.sh first"
[[ -f "$CASE_DIR/Allmesh" ]] || die "No Allmesh in $CASE_DIR — run 01_prepare_case.sh"

info "Meshing $CASE_DIR with ${NPROCS} ranks (preset=${MESH_PRESET})"
of_run 'chmod +x Allmesh Allrun Allclean 2>/dev/null; ./Allmesh'
info "Mesh complete. Check logs: log.snappyHexMesh, log.blockMesh"
info "Next: $DIR/03_run.sh"

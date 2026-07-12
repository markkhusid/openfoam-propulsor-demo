#!/usr/bin/env bash
# Full pipeline: prepare → mesh → run → movie → efficiency
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

CFG="${1:-}"
load_config "$CFG"

"$DIR/00_check_deps.sh"
"$DIR/01_prepare_case.sh" "$PIPELINE_CONFIG"
"$DIR/02_mesh.sh" "$PIPELINE_CONFIG"
"$DIR/03_run.sh" "$PIPELINE_CONFIG"
"$DIR/04_movie.sh" "$PIPELINE_CONFIG" || warn "Movie step failed — check surface samples / ParaView"
"$DIR/05_efficiency.sh" "$PIPELINE_CONFIG" || warn "Efficiency step failed — check forces.dat"

info "All done."
info "Case:   $CASE_DIR"
info "Movie:  $CASE_DIR/movies/propulsor_flow.mp4"
info "Plots:  $CASE_DIR/postProcessing/plots/"

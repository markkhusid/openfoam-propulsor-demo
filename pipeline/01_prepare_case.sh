#!/usr/bin/env bash
# Create / refresh an OpenFOAM case from config.env + STL paths.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

CFG="${1:-}"
load_config "$CFG"
preset_defaults

[[ -n "${ROTOR_STL:-}" ]] || die "Set ROTOR_STL in config.env to your watertight rotor/pumpjet STL"
[[ -f "$ROTOR_STL" ]] || die "ROTOR_STL not found: $ROTOR_STL"

mkdir -p "$CASE_DIR"
info "Preparing case at $CASE_DIR"
info "Mesh preset: ${MESH_PRESET}  nprocs=${NPROCS}  rpm=${RPM}"

export CASE_DIR ROTOR_STL STATOR_STLS STL_SCALE
export RPM ROT_AXIS ROT_ORIGIN U_INF NU RHO_INF
export DOMAIN_UPSTREAM_D DOMAIN_DOWNSTREAM_D DOMAIN_RADIUS_D
export ROTZONE_RADIUS_FACTOR ROTZONE_HALF_LENGTH_D CHAR_DIAMETER
export BLOCK_NX BLOCK_NY BLOCK_NZ
export REFINE_ROTOR_MIN REFINE_ROTOR_MAX REFINE_STATOR_MIN REFINE_STATOR_MAX
export REFINE_ROTZONE MAX_GLOBAL_CELLS MAX_LOCAL_CELLS NPROCS
export N_REVOLUTIONS MAX_CO VOLUME_WRITE_PER_REV PURGE_WRITE
export MOVIE_DURATION_SEC MOVIE_FPS MOVIE_FRAMES Q_ISO_VALUE
export MESH_PRESET

PYTHONPATH="$DIR/lib${PYTHONPATH:+:$PYTHONPATH}" \
  python3 "$DIR/lib/write_case.py"

# Copy config snapshot into the case for reproducibility
cp -f "${PIPELINE_CONFIG}" "$CASE_DIR/config.env.used"

info "Case ready: $CASE_DIR"
info "Next: $DIR/02_mesh.sh"

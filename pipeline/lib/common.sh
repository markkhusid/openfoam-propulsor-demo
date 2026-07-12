#!/usr/bin/env bash
# Shared helpers for the propulsor pipeline.
# shellcheck disable=SC1091

set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$PIPELINE_DIR/.." && pwd)"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }
warn() { echo "WARN: $*" >&2; }

load_config() {
  local cfg="${1:-}"
  if [[ -z "$cfg" ]]; then
    if [[ -f "$PWD/config.env" ]]; then
      cfg="$PWD/config.env"
    elif [[ -f "$PIPELINE_DIR/config.env" ]]; then
      cfg="$PIPELINE_DIR/config.env"
    else
      die "No config.env found. Copy pipeline/config.env.example → config.env and edit it."
    fi
  fi
  [[ -f "$cfg" ]] || die "Config not found: $cfg"
  # shellcheck source=/dev/null
  set -a
  source "$cfg"
  set +a
  export PIPELINE_CONFIG="$cfg"
  info "Loaded config: $cfg"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

# Run a shell command string inside OpenFOAM environment (native or Docker).
# Usage: of_run "blockMesh"   or   of_run './Allmesh'
of_run() {
  local cmd="$*"
  [[ -n "${CASE_DIR:-}" ]] || die "CASE_DIR not set"
  [[ -d "$CASE_DIR" ]] || die "CASE_DIR does not exist: $CASE_DIR"

  case "${OF_MODE:-docker}" in
    native)
      # Assume environment already sourced by user
      command -v blockMesh >/dev/null 2>&1 || die "Native mode: OpenFOAM not in PATH (source etc/bashrc first)"
      (cd "$CASE_DIR" && bash -lc "$cmd")
      ;;
    docker)
      require_cmd docker
      local image="${OF_IMAGE:-openfoam/openfoam11-paraview510:latest}"
      local uid gid
      uid="$(id -u)"
      gid="$(id -g)"
      docker run --rm --shm-size=4g \
        -u "${uid}:${gid}" \
        -v "$CASE_DIR:/home/openfoam/work" \
        -v "$REPO_ROOT:/home/openfoam/repo:ro" \
        --workdir /home/openfoam/work \
        --entrypoint bash \
        "$image" \
        -c "source /opt/openfoam11/etc/bashrc 2>/dev/null || source /usr/lib/openfoam/*/etc/bashrc 2>/dev/null || true; $cmd"
      ;;
    wrapper)
      local bin="${OPENFOAM_BIN:-$HOME/bin/openfoam}"
      [[ -x "$bin" ]] || die "OPENFOAM_BIN not executable: $bin"
      (cd "$CASE_DIR" && "$bin" -c "$cmd")
      ;;
    *)
      die "Unknown OF_MODE=${OF_MODE}. Use docker|native|wrapper"
      ;;
  esac
}

bytes_of() { du -sb "$1" 2>/dev/null | awk '{print $1}'; }

preset_defaults() {
  # Populate mesh knobs from MESH_PRESET if custom vars empty.
  case "${MESH_PRESET:-demo}" in
    demo)
      : "${BLOCK_NX:=20}"
      : "${BLOCK_NY:=24}"
      : "${BLOCK_NZ:=20}"
      : "${REFINE_ROTOR_MIN:=3}"
      : "${REFINE_ROTOR_MAX:=4}"
      : "${REFINE_STATOR_MIN:=2}"
      : "${REFINE_STATOR_MAX:=3}"
      : "${REFINE_ROTZONE:=3}"
      : "${MAX_GLOBAL_CELLS:=600000}"
      : "${MAX_LOCAL_CELLS:=80000}"
      : "${NPROCS:=4}"
      ;;
    engineering)
      : "${BLOCK_NX:=36}"
      : "${BLOCK_NY:=48}"
      : "${BLOCK_NZ:=36}"
      : "${REFINE_ROTOR_MIN:=4}"
      : "${REFINE_ROTOR_MAX:=5}"
      : "${REFINE_STATOR_MIN:=3}"
      : "${REFINE_STATOR_MAX:=4}"
      : "${REFINE_ROTZONE:=4}"
      : "${MAX_GLOBAL_CELLS:=5000000}"
      : "${MAX_LOCAL_CELLS:=200000}"
      : "${NPROCS:=16}"
      ;;
    fine)
      : "${BLOCK_NX:=48}"
      : "${BLOCK_NY:=64}"
      : "${BLOCK_NZ:=48}"
      : "${REFINE_ROTOR_MIN:=5}"
      : "${REFINE_ROTOR_MAX:=6}"
      : "${REFINE_STATOR_MIN:=4}"
      : "${REFINE_STATOR_MAX:=5}"
      : "${REFINE_ROTZONE:=5}"
      : "${MAX_GLOBAL_CELLS:=20000000}"
      : "${MAX_LOCAL_CELLS:=400000}"
      : "${NPROCS:=64}"
      ;;
    custom)
      : "${BLOCK_NX:=24}"
      : "${BLOCK_NY:=32}"
      : "${BLOCK_NZ:=24}"
      : "${REFINE_ROTOR_MIN:=3}"
      : "${REFINE_ROTOR_MAX:=4}"
      : "${REFINE_STATOR_MIN:=2}"
      : "${REFINE_STATOR_MAX:=3}"
      : "${REFINE_ROTZONE:=3}"
      : "${MAX_GLOBAL_CELLS:=2000000}"
      : "${MAX_LOCAL_CELLS:=100000}"
      : "${NPROCS:=8}"
      ;;
    *)
      die "Unknown MESH_PRESET=${MESH_PRESET} (demo|engineering|fine|custom)"
      ;;
  esac
  export BLOCK_NX BLOCK_NY BLOCK_NZ
  export REFINE_ROTOR_MIN REFINE_ROTOR_MAX REFINE_STATOR_MIN REFINE_STATOR_MAX
  export REFINE_ROTZONE MAX_GLOBAL_CELLS MAX_LOCAL_CELLS NPROCS
}

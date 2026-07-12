#!/usr/bin/env bash
# Verify host tools for the propulsor pipeline.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

info "Checking pipeline dependencies"

ok=0
need() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "  OK  $1 ($({ command -v "$1"; } 2>/dev/null))"
  else
    echo "  MISSING  $1"
    ok=1
  fi
}

need python3
need ffmpeg
python3 - <<'PY' || ok=1
import numpy, matplotlib
print("  OK  python3 modules: numpy, matplotlib")
PY

case "${OF_MODE:-docker}" in
  docker)
    need docker
    if docker image inspect "${OF_IMAGE:-openfoam/openfoam11-paraview510:latest}" >/dev/null 2>&1; then
      echo "  OK  docker image ${OF_IMAGE:-openfoam/openfoam11-paraview510:latest}"
    else
      echo "  WARN docker image not pulled yet: ${OF_IMAGE:-openfoam/openfoam11-paraview510:latest}"
      echo "       run: docker pull ${OF_IMAGE:-openfoam/openfoam11-paraview510:latest}"
    fi
    ;;
  native)
    if command -v blockMesh >/dev/null 2>&1; then
      echo "  OK  native OpenFOAM (blockMesh in PATH)"
    else
      echo "  MISSING native OpenFOAM — source etc/bashrc first"
      ok=1
    fi
    ;;
  wrapper)
    bin="${OPENFOAM_BIN:-$HOME/bin/openfoam}"
    if [[ -x "$bin" ]]; then
      echo "  OK  wrapper $bin"
    else
      echo "  MISSING OPENFOAM_BIN=$bin"
      ok=1
    fi
    ;;
esac

if [[ $ok -ne 0 ]]; then
  die "Dependency check failed"
fi
info "Dependencies look good"

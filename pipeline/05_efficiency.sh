#!/usr/bin/env bash
# Plot efficiency, thrust, and torque vs time from forces.dat
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

load_config "${1:-}"
[[ -d "${CASE_DIR:-}" ]] || die "CASE_DIR missing"

forces=$(find "$CASE_DIR/postProcessing/forces" -name forces.dat 2>/dev/null | head -1 || true)
[[ -n "$forces" && -f "$forces" ]] || die "No forces.dat under $CASE_DIR/postProcessing/forces"

meta="$CASE_DIR/pipeline_meta.json"
out="$CASE_DIR/postProcessing/plots"
mkdir -p "$out"

# shellcheck disable=SC2206
axis_arr=(${ROT_AXIS:-0 1 0})
# shellcheck disable=SC2206
u_arr=(${U_INF:-0 -5 0})

args=(
  --forces "$forces"
  --out-dir "$out"
  --rpm "${RPM:-1500}"
  --axis "${axis_arr[0]}" "${axis_arr[1]}" "${axis_arr[2]}"
  --u-inf "${u_arr[0]}" "${u_arr[1]}" "${u_arr[2]}"
)
if [[ -f "$meta" ]]; then
  args+=(--meta "$meta")
fi

python3 "$DIR/lib/plot_forces.py" "${args[@]}"

info "Plots written to $out"
ls -lh "$out"/propulsor_*.png "$out"/propulsor_*.pdf "$out"/*.csv 2>/dev/null || ls -lh "$out"

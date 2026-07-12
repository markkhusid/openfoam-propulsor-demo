#!/usr/bin/env bash
# Disk-capped propeller run + post-process movie pipeline.
# Budget: keep case growth under MAX_GB (default 10).
set -euo pipefail

CASE="$(cd "$(dirname "$0")" && pwd)"
cd "$CASE"
export PATH="${HOME}/bin:${PATH}"
OPENFOAM="${OPENFOAM_BIN:-$HOME/bin/openfoam}"
MAX_GB="${MAX_GB:-10}"
LOG="$CASE/log.run_and_movie"
DISK_LOG="$CASE/log.disk_watch"

exec > >(tee -a "$LOG") 2>&1

echo "=============================================="
echo "Propeller run started: $(date -Is)"
echo "Case: $CASE"
echo "Disk budget: ${MAX_GB} GB (case directory)"
echo "=============================================="

bytes_of() { du -sb "$1" 2>/dev/null | awk '{print $1}'; }
gb_of() { python3 -c "print('{:.3f}'.format($(bytes_of "$1")/1e9))"; }

start_bytes=$(bytes_of "$CASE")
echo "Case size at start: $(gb_of "$CASE") GB"

# Clean prior results but keep mesh (processor*/constant)
echo "Cleaning prior fields/results..."
rm -rf "$CASE"/postProcessing "$CASE"/movies/frames \
  "$CASE"/log.foamRun "$CASE"/log.reconstructPar \
  "$CASE"/log.decomposePar_fields 2>/dev/null || true
# remove time dirs and fields from processors; keep constant/
for d in "$CASE"/processor*; do
  [[ -d "$d" ]] || continue
  find "$d" -maxdepth 1 -mindepth 1 ! -name constant -exec rm -rf {} +
done
# remove reconstructed volume times at case root except 0/
find "$CASE" -maxdepth 1 -type d \( -name '[1-9]*' -o -name '0.*' \) -exec rm -rf {} +

# Disk watchdog (background)
(
  while true; do
    sz=$(bytes_of "$CASE")
    gb=$(python3 -c "print('{:.3f}'.format($sz/1e9))")
    free=$(df -B1 / | awk 'NR==2{print $4}')
    free_gb=$(python3 -c "print('{:.3f}'.format($free/1e9))")
    echo "$(date -Is) case_GB=$gb free_GB=$free_gb" >> "$DISK_LOG"
    # stop if case exceeds budget or free disk < 2 GB
    python3 - <<PY
import sys
sz=$sz
free=$free
max_b=int(float("$MAX_GB")*1e9)
if sz > max_b or free < 2*10**9:
    sys.exit(1)
sys.exit(0)
PY
    if [[ $? -ne 0 ]]; then
      echo "$(date -Is) DISK LIMIT — signalling foamRun" >> "$DISK_LOG"
      pkill -f "foamRun -parallel" 2>/dev/null || true
      exit 0
    fi
    sleep 30
  done
) &
WATCH_PID=$!
trap 'kill $WATCH_PID 2>/dev/null || true' EXIT

echo "Decomposing fields..."
"$OPENFOAM" -c 'decomposePar -fields -copyZero' | tee "$CASE/log.decomposePar_fields"

echo "Running foamRun (4 ranks)..."
set +e
"$OPENFOAM" -c 'mpirun --oversubscribe -np 4 foamRun -parallel' | tee "$CASE/log.foamRun"
RUN_RC=${PIPESTATUS[0]}
set -e
echo "foamRun exit: $RUN_RC"

kill $WATCH_PID 2>/dev/null || true

echo "Case size after solve: $(gb_of "$CASE") GB"
df -h / | tail -1

# Collect surface samples to case-level postProcessing if only on processors
if [[ ! -d "$CASE/postProcessing/surfaces" ]]; then
  echo "Gathering processor surface samples..."
  mkdir -p "$CASE/postProcessing"
  if [[ -d "$CASE/processor0/postProcessing/surfaces" ]]; then
    # Prefer processor0 full series if collated there; else merge is complex — use p0
    cp -a "$CASE/processor0/postProcessing/surfaces" "$CASE/postProcessing/" 2>/dev/null || true
  fi
fi

echo "Surface sample inventory:"
find "$CASE" -path '*/postProcessing/surfaces/*' -name '*.vtp' 2>/dev/null | wc -l
find "$CASE/processor0/postProcessing/surfaces" -type d 2>/dev/null | head -20 || true
ls -la "$CASE/postProcessing/surfaces" 2>/dev/null || true

echo "Rendering frames with ParaView (pvpython)..."
"$OPENFOAM" -c 'pvpython make_movie.py' || {
  echo "pvpython make_movie.py failed — trying alternate discovery"
  find "$CASE" -name '*.vtp' 2>/dev/null | head -30
}

echo "Encoding MP4..."
bash "$CASE/encode_movie.sh" || true

echo "=============================================="
echo "Finished: $(date -Is)"
echo "Case size final: $(gb_of "$CASE") GB"
ls -lh "$CASE/movies/"*.mp4 2>/dev/null || echo "MP4 not produced yet"
echo "=============================================="
exit "$RUN_RC"

#!/usr/bin/env bash
# Build MP4 from surface VTK samples (ParaView pvpython + ffmpeg).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

load_config "${1:-}"
[[ -d "${CASE_DIR:-}" ]] || die "CASE_DIR missing"

surf="$CASE_DIR/postProcessing/surfaces"
if [[ ! -d "$surf" ]]; then
  die "No surface samples at $surf — did 03_run.sh finish with system/surfaces enabled?"
fi

n=$(find "$surf" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)
info "Found ~$n surface time directories"
[[ "$n" -gt 2 ]] || die "Too few surface samples ($n) for a movie"

fps="${MOVIE_FPS:-16}"
dur="${MOVIE_DURATION_SEC:-10}"
w="${MOVIE_WIDTH:-1280}"
h="${MOVIE_HEIGHT:-720}"
export CASE_DIR MOVIE_FPS MOVIE_WIDTH MOVIE_HEIGHT MOVIE_FIELD

info "Rendering frames with ParaView (pvpython)..."
cp -f "$DIR/lib/make_movie.py" "$CASE_DIR/make_movie.py"
of_run "export CASE_DIR=/home/openfoam/work MOVIE_FPS=$fps MOVIE_WIDTH=$w MOVIE_HEIGHT=$h MOVIE_FIELD=${MOVIE_FIELD:-U}; pvpython make_movie.py"

frames="$CASE_DIR/movies/frames"
# Normalize any leftover odd names
python3 - <<PY
import re
from pathlib import Path
d = Path(r"""$frames""")
if not d.is_dir():
    raise SystemExit("No frames directory")
for f in list(d.glob("frame*.png")):
    m = re.search(r"(\d+)\.png$", f.name)
    if not m:
        continue
    dest = d / ("frame_%04d.png" % int(m.group(1)))
    if f.resolve() != dest.resolve():
        if dest.exists():
            dest.unlink()
        f.rename(dest)
n = len(list(d.glob("frame_[0-9][0-9][0-9][0-9].png")))
print("normalized frames:", n)
if n < 2:
    raise SystemExit("Not enough PNG frames")
PY

require_cmd ffmpeg
mp4="$CASE_DIR/movies/propulsor_flow.mp4"
info "Encoding ${dur}s MP4 @ ${fps} fps → $mp4"

# If we have fewer unique frames than dur*fps, slow playback (lower fps) to fill duration
nframes=$(ls -1 "$frames"/frame_[0-9][0-9][0-9][0-9].png | wc -l)
play_fps=$(python3 - <<PY
n=$nframes
dur=float("$dur")
fps=float("$fps")
# Use configured fps but stretch to at least dur seconds
import math
need = max(1.0, n / dur)
# if n/fps < dur, reduce fps so duration >= dur
if n / fps < dur:
    print(max(1.0, n / dur))
else:
    print(fps)
PY
)

ffmpeg -y -hide_banner -loglevel warning \
  -framerate "$play_fps" \
  -i "$frames/frame_%04d.png" \
  -vf "scale=${w}:${h}:flags=lanczos,format=yuv420p" \
  -c:v libx264 -preset medium -crf 20 \
  -movflags +faststart \
  -t "$dur" \
  "$mp4"

# Convenience copy at case root
cp -f "$mp4" "$CASE_DIR/propulsor_flow_${dur%.0f}s.mp4" 2>/dev/null \
  || cp -f "$mp4" "$CASE_DIR/propulsor_flow.mp4"

ls -lh "$mp4"
ffprobe -hide_banner "$mp4" 2>&1 | head -15 || true
info "Movie ready: $mp4"

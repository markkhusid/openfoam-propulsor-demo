#!/usr/bin/env bash
# Encode PNG frames (or loop them) into a >=10 s H.264 MP4.
set -euo pipefail
CASE="$(cd "$(dirname "$0")" && pwd)"
OUT="$CASE/movies"
FRAMES="$OUT/frames"
MP4="$OUT/propeller_flow_10s.mp4"
META="$OUT/movie_meta.txt"

if [[ ! -d "$FRAMES" ]] || ! ls "$FRAMES"/frame_*.png >/dev/null 2>&1; then
  echo "No frames in $FRAMES — run make_movie.py first" >&2
  exit 1
fi

# ParaView sometimes writes frame_%04d.0000.png (literal %04d). Normalize names.
python3 - <<'PY'
import re
from pathlib import Path
d = Path(r"""$FRAMES""")
for f in list(d.glob('frame_*.png')):
    m = re.search(r'(\d+)\.png$', f.name)
    if not m:
        continue
    dest = d / f'frame_{int(m.group(1)):04d}.png'
    if f.resolve() != dest.resolve():
        if dest.exists():
            dest.unlink()
        f.rename(dest)
PY

n=$(ls -1 "$FRAMES"/frame_[0-9][0-9][0-9][0-9].png 2>/dev/null | wc -l)
fps=16
if [[ -f "$META" ]]; then
  fps=$(grep -E '^fps=' "$META" | cut -d= -f2 || echo 16)
fi
dur=$(python3 -c "print(round($n/float(max(1,int('$fps'))),3))")
echo "Frames: $n  fps: $fps  duration: ${dur}s"

ffmpeg -y -hide_banner -loglevel warning \
  -framerate "$fps" \
  -i "$FRAMES/frame_%04d.png" \
  -vf "scale=1280:720:flags=lanczos,format=yuv420p" \
  -c:v libx264 -preset medium -crf 20 \
  -movflags +faststart \
  -t 10 \
  "$MP4"

ls -lh "$MP4"
ffprobe -hide_banner "$MP4" 2>&1 | head -20
echo "Movie ready: $MP4"

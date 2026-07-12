#!/usr/bin/env python3
"""
Fallback movie generator using matplotlib (no ParaView/OpenGL).

Reads OpenFOAM surface function-object legacy VTK polydata and builds
an MP4 via ffmpeg (PNG frame sequence).
"""
from __future__ import annotations

import re
import struct
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.tri import Triangulation


def read_legacy_vtk_polydata(path: Path) -> Dict[str, np.ndarray]:
    """Minimal binary/ascii VTK POLYDATA reader for OF surface samples."""
    raw = path.read_bytes()
    # Try ascii first
    try:
        text = raw.decode("utf-8")
        if "POINTS" in text and "POLYGONS" in text or "TRIANGLE_STRIPS" in text or "CELLS" in text:
            return _read_ascii_vtk(text)
    except UnicodeDecodeError:
        pass
    return _read_binary_vtk(raw)


def _read_ascii_vtk(text: str) -> Dict[str, np.ndarray]:
    lines = text.splitlines()
    i = 0
    points = None
    polys = []
    point_data: Dict[str, np.ndarray] = {}
    n_pts = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("POINTS"):
            parts = line.split()
            n_pts = int(parts[1])
            vals: List[float] = []
            i += 1
            while len(vals) < n_pts * 3 and i < len(lines):
                vals.extend(float(x) for x in lines[i].split())
                i += 1
            points = np.asarray(vals, dtype=float).reshape(n_pts, 3)
            continue
        if line.startswith("POLYGONS") or line.startswith("CELLS"):
            parts = line.split()
            n_cells = int(parts[1])
            i += 1
            for _ in range(n_cells):
                nums = [int(x) for x in lines[i].split()]
                i += 1
                n = nums[0]
                ids = nums[1 : 1 + n]
                if n == 3:
                    polys.append(ids)
                elif n == 4:
                    polys.append([ids[0], ids[1], ids[2]])
                    polys.append([ids[0], ids[2], ids[3]])
            continue
        if line.startswith("POINT_DATA"):
            i += 1
            continue
        if line.startswith("SCALARS") or line.startswith("VECTORS"):
            kind = "V" if line.startswith("VECTORS") else "S"
            name = line.split()[1]
            if kind == "S":
                # skip LOOKUP_TABLE line if present
                i += 1
                if i < len(lines) and lines[i].strip().startswith("LOOKUP"):
                    i += 1
                vals = []
                while len(vals) < n_pts and i < len(lines):
                    vals.extend(float(x) for x in lines[i].split())
                    i += 1
                point_data[name] = np.asarray(vals[:n_pts], dtype=float)
            else:
                i += 1
                vals = []
                while len(vals) < n_pts * 3 and i < len(lines):
                    vals.extend(float(x) for x in lines[i].split())
                    i += 1
                point_data[name] = np.asarray(vals[: n_pts * 3], dtype=float).reshape(n_pts, 3)
            continue
        if line.startswith("FIELD"):
            # skip generic FIELD blocks
            i += 1
            continue
        i += 1
    if points is None:
        raise ValueError("No POINTS in VTK")
    return {
        "points": points,
        "tris": np.asarray(polys, dtype=int) if polys else np.zeros((0, 3), int),
        "data": point_data,
    }


def _read_binary_vtk(raw: bytes) -> Dict[str, np.ndarray]:
    # OpenFOAM binary VTK: header ascii until blank line then binary blobs
    # Find "POINTS n float\n" then binary floats big-endian
    header_end = raw.find(b"\n")
    # Split header
    # Search for POINTS
    m = re.search(rb"POINTS\s+(\d+)\s+(\w+)\s*\n", raw)
    if not m:
        raise ValueError("binary VTK: POINTS not found")
    n_pts = int(m.group(1))
    dtype = m.group(2).decode()
    pos = m.end()
    if dtype.lower() == "float":
        pts = np.frombuffer(raw, dtype=">f4", count=n_pts * 3, offset=pos).astype(np.float64)
        pos += n_pts * 3 * 4
    else:
        pts = np.frombuffer(raw, dtype=">f8", count=n_pts * 3, offset=pos)
        pos += n_pts * 3 * 8
    points = pts.reshape(n_pts, 3)

    # POLYGONS
    m2 = re.search(rb"POLYGONS\s+(\d+)\s+(\d+)\s*\n", raw[pos:])
    polys = []
    if m2:
        n_cells = int(m2.group(1))
        n_ints = int(m2.group(2))
        pos2 = pos + m2.end()
        ints = np.frombuffer(raw, dtype=">i4", count=n_ints, offset=pos2)
        j = 0
        for _ in range(n_cells):
            n = int(ints[j])
            ids = ints[j + 1 : j + 1 + n].tolist()
            j += 1 + n
            if n >= 3:
                for k in range(1, n - 1):
                    polys.append([ids[0], ids[k], ids[k + 1]])
        pos = pos2 + n_ints * 4

    # POINT_DATA / VECTORS U / SCALARS p
    data: Dict[str, np.ndarray] = {}
    rest = raw[pos:]
    for vm in re.finditer(rb"VECTORS\s+(\S+)\s+(\w+)\s*\n", rest):
        name = vm.group(1).decode()
        dt = vm.group(2).decode().lower()
        off = pos + vm.end()
        if dt == "float":
            arr = np.frombuffer(raw, dtype=">f4", count=n_pts * 3, offset=off).astype(np.float64)
        else:
            arr = np.frombuffer(raw, dtype=">f8", count=n_pts * 3, offset=off)
        data[name] = arr.reshape(n_pts, 3)
    for sm in re.finditer(rb"SCALARS\s+(\S+)\s+(\w+)", rest):
        name = sm.group(1).decode()
        # skip to after LOOKUP_TABLE line
        after = rest[sm.end() :]
        nl = after.find(b"\n")
        after2 = after[nl + 1 :]
        if after2.startswith(b"LOOKUP"):
            nl2 = after2.find(b"\n")
            data_off = pos + sm.end() + nl + 1 + nl2 + 1
        else:
            data_off = pos + sm.end() + nl + 1
        dt = sm.group(2).decode().lower()
        try:
            if dt == "float":
                arr = np.frombuffer(raw, dtype=">f4", count=n_pts, offset=data_off).astype(np.float64)
            else:
                arr = np.frombuffer(raw, dtype=">f8", count=n_pts, offset=data_off)
            data[name] = arr
        except Exception:
            pass

    return {"points": points, "tris": np.asarray(polys, dtype=int) if polys else np.zeros((0, 3), int), "data": data}


def list_times(surf_root: Path) -> List[Tuple[float, Path]]:
    out = []
    for d in surf_root.iterdir():
        if not d.is_dir():
            continue
        try:
            out.append((float(d.name), d))
        except ValueError:
            continue
    out.sort(key=lambda x: x[0])
    return out


def main():
    import os

    case = Path(os.environ.get("CASE_DIR", ".")).resolve()
    surf = case / "postProcessing" / "surfaces"
    if not surf.is_dir():
        raise SystemExit(f"No surfaces at {surf}")

    times = list_times(surf)
    if len(times) < 2:
        raise SystemExit(f"Need >=2 surface times, found {len(times)}")

    # prefer cutA then zNormal
    sample_name = None
    for name in ("cutA", "zNormal", "cutB", "yNormal"):
        if (times[0][1] / f"{name}.vtk").is_file() or (times[0][1] / f"{name}.vtp").is_file():
            sample_name = name
            break
    if sample_name is None:
        # first vtk in folder
        v = list(times[0][1].glob("*.vtk"))
        if not v:
            raise SystemExit("No vtk surfaces found")
        sample_name = v[0].stem

    frames_dir = case / "movies" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()

    # Color scale from mid-run sample
    mid = times[len(times) // 2][1] / f"{sample_name}.vtk"
    if not mid.is_file():
        mid = times[len(times) // 2][1] / f"{sample_name}.vtp"
    mid_data = read_legacy_vtk_polydata(mid)
    U = mid_data["data"].get("U")
    if U is not None and U.ndim == 2:
        umag = np.linalg.norm(U, axis=1)
    else:
        umag = mid_data["data"].get("p", np.zeros(len(mid_data["points"])))
    vmin, vmax = np.percentile(umag, [2, 98])
    if vmax <= vmin:
        vmax = vmin + 1.0

    w = int(os.environ.get("MOVIE_WIDTH", 1280))
    h = int(os.environ.get("MOVIE_HEIGHT", 720))
    dpi = 100
    fig_w, fig_h = w / dpi, h / dpi

    for fi, (tval, tdir) in enumerate(times):
        fpath = tdir / f"{sample_name}.vtk"
        if not fpath.is_file():
            fpath = tdir / f"{sample_name}.vtp"
        try:
            data = read_legacy_vtk_polydata(fpath)
        except Exception as e:
            print("skip", fpath, e)
            continue
        pts = data["points"]
        tris = data["tris"]
        U = data["data"].get("U")
        if U is not None and getattr(U, "ndim", 0) == 2:
            scalar = np.linalg.norm(U, axis=1)
            label = "|U| [m/s]"
        else:
            scalar = data["data"].get("p", np.zeros(len(pts)))
            label = "p"
        # project to best 2D plane (drop axis with smallest variance)
        var = pts.var(axis=0)
        drop = int(np.argmin(var))
        keep = [i for i in range(3) if i != drop]
        xy = pts[:, keep]
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        if len(tris) > 0:
            tri = Triangulation(xy[:, 0], xy[:, 1], tris)
            tcf = ax.tripcolor(tri, scalar, shading="gouraud", cmap="coolwarm", vmin=vmin, vmax=vmax)
        else:
            tcf = ax.scatter(xy[:, 0], xy[:, 1], c=scalar, s=2, cmap="coolwarm", vmin=vmin, vmax=vmax)
        cb = fig.colorbar(tcf, ax=ax, fraction=0.046, pad=0.04)
        cb.set_label(label)
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(f"Pumpjet demo — {sample_name}  t = {tval:.5g} s")
        ax.set_xlabel("x [m]" if keep[0] == 0 else ("y [m]" if keep[0] == 1 else "z [m]"))
        ax.set_ylabel("x [m]" if keep[1] == 0 else ("y [m]" if keep[1] == 1 else "z [m]"))
        ax.set_facecolor("#101820")
        fig.tight_layout()
        out = frames_dir / f"frame_{fi:04d}.png"
        fig.savefig(out, dpi=dpi, facecolor="#0b0f14")
        plt.close(fig)
        if fi % 10 == 0:
            print(f"frame {fi}/{len(times)} t={tval}")

    n = len(list(frames_dir.glob("frame_*.png")))
    print("frames", n)
    fps = float(os.environ.get("MOVIE_FPS", 16))
    dur = float(os.environ.get("MOVIE_DURATION_SEC", 10))
    play_fps = max(1.0, n / dur)
    mp4 = case / "movies" / "propulsor_flow.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-framerate",
        str(play_fps),
        "-i",
        str(frames_dir / "frame_%04d.png"),
        "-vf",
        f"scale={w}:{h}:flags=lanczos,format=yuv420p",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "20",
        "-movflags",
        "+faststart",
        "-t",
        str(dur),
        str(mp4),
    ]
    subprocess.check_call(cmd)
    print("Wrote", mp4)
    # convenience
    (case / f"propulsor_flow_{int(dur)}s.mp4").write_bytes(mp4.read_bytes())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Fallback movie generator using matplotlib (no ParaView/OpenGL).

Reads OpenFOAM surface function-object legacy VTK polydata (BINARY FIELD
attributes format) and builds an MP4 via ffmpeg.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.tri import Triangulation


def read_legacy_vtk_polydata(path: Path) -> Dict[str, np.ndarray]:
    raw = Path(path).read_bytes()
    # Prefer binary path if marker present
    if b"\nBINARY\n" in raw[:200] or raw.find(b"BINARY") < 80:
        return _read_binary_vtk(raw)
    try:
        text = raw.decode("utf-8", errors="strict")
        if "POINTS" in text:
            return _read_ascii_vtk(text)
    except Exception:
        pass
    return _read_binary_vtk(raw)


def _read_ascii_vtk(text: str) -> Dict[str, np.ndarray]:
    lines = text.splitlines()
    i = 0
    points = None
    polys: List[List[int]] = []
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
            n_cells = int(line.split()[1])
            i += 1
            for _ in range(n_cells):
                nums = [int(x) for x in lines[i].split()]
                i += 1
                n, ids = nums[0], nums[1:]
                if n >= 3:
                    for k in range(1, n - 1):
                        polys.append([ids[0], ids[k], ids[k + 1]])
            continue
        if line.startswith("POINT_DATA"):
            i += 1
            continue
        if line.startswith("FIELD"):
            # FIELD attributes N
            n_arrays = int(line.split()[-1]) if line.split()[-1].isdigit() else 0
            i += 1
            for _ in range(n_arrays):
                # name nComp nTuples type
                while i < len(lines) and not lines[i].strip():
                    i += 1
                hdr = lines[i].split()
                i += 1
                name, ncomp, ntup = hdr[0], int(hdr[1]), int(hdr[2])
                need = ncomp * ntup
                vals = []
                while len(vals) < need and i < len(lines):
                    vals.extend(float(x) for x in lines[i].split())
                    i += 1
                arr = np.asarray(vals[:need], dtype=float)
                point_data[name] = arr.reshape(ntup, ncomp) if ncomp > 1 else arr
            continue
        if line.startswith("SCALARS"):
            name = line.split()[1]
            i += 1
            if i < len(lines) and lines[i].strip().startswith("LOOKUP"):
                i += 1
            vals = []
            while len(vals) < n_pts and i < len(lines):
                vals.extend(float(x) for x in lines[i].split())
                i += 1
            point_data[name] = np.asarray(vals[:n_pts], dtype=float)
            continue
        if line.startswith("VECTORS"):
            name = line.split()[1]
            i += 1
            vals = []
            while len(vals) < n_pts * 3 and i < len(lines):
                vals.extend(float(x) for x in lines[i].split())
                i += 1
            point_data[name] = np.asarray(vals[: n_pts * 3], dtype=float).reshape(n_pts, 3)
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
    """OpenFOAM sampleSurface BINARY POLYDATA with FIELD attributes."""
    m = re.search(rb"POINTS\s+(\d+)\s+(\w+)\s*\n", raw)
    if not m:
        raise ValueError("binary VTK: POINTS not found")
    n_pts = int(m.group(1))
    dtype = m.group(2).decode().lower()
    pos = m.end()
    if dtype == "float":
        pts = np.frombuffer(raw, dtype=">f4", count=n_pts * 3, offset=pos).astype(np.float64)
        pos += n_pts * 3 * 4
    else:
        pts = np.frombuffer(raw, dtype=">f8", count=n_pts * 3, offset=pos)
        pos += n_pts * 3 * 8
    points = pts.reshape(n_pts, 3)

    # Optional newline after binary blob
    while pos < len(raw) and raw[pos : pos + 1] in (b"\n", b"\r"):
        pos += 1

    polys: List[List[int]] = []
    m2 = re.search(rb"POLYGONS\s+(\d+)\s+(\d+)\s*\n", raw[pos:])
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

    while pos < len(raw) and raw[pos : pos + 1] in (b"\n", b"\r"):
        pos += 1

    data: Dict[str, np.ndarray] = {}
    # POINT_DATA n\nFIELD attributes N\n
    m3 = re.search(rb"POINT_DATA\s+(\d+)\s*\n", raw[pos:])
    if m3:
        pos = pos + m3.end()
        m4 = re.search(rb"FIELD\s+\w+\s+(\d+)\s*\n", raw[pos:])
        if m4:
            n_arrays = int(m4.group(1))
            pos = pos + m4.end()
            for _ in range(n_arrays):
                # name nComp nTuples type\n then binary
                # e.g. "p 1 3733 float\n" or "U 3 3733 float\n"
                # may have leading newline
                while pos < len(raw) and raw[pos : pos + 1] in (b"\n", b"\r"):
                    pos += 1
                nl = raw.find(b"\n", pos)
                if nl < 0:
                    break
                hdr = raw[pos:nl].decode("ascii", errors="ignore").split()
                pos = nl + 1
                if len(hdr) < 4:
                    break
                name, ncomp, ntup, typ = hdr[0], int(hdr[1]), int(hdr[2]), hdr[3].lower()
                count = ncomp * ntup
                if typ == "float":
                    arr = np.frombuffer(raw, dtype=">f4", count=count, offset=pos).astype(np.float64)
                    pos += count * 4
                elif typ in ("double",):
                    arr = np.frombuffer(raw, dtype=">f8", count=count, offset=pos)
                    pos += count * 8
                else:
                    # skip unknown
                    break
                data[name] = arr.reshape(ntup, ncomp) if ncomp > 1 else arr

    return {
        "points": points,
        "tris": np.asarray(polys, dtype=int) if polys else np.zeros((0, 3), int),
        "data": data,
    }


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


def pick_surface(tdir: Path) -> str:
    for name in ("cutA", "cutB", "zNormal", "yNormal", "rotor"):
        if (tdir / f"{name}.vtk").is_file():
            return name
    v = list(tdir.glob("*.vtk"))
    if not v:
        raise SystemExit(f"No vtk in {tdir}")
    return v[0].stem


def scalar_from_data(data: dict) -> Tuple[np.ndarray, str]:
    d = data["data"]
    if "U" in d:
        U = np.asarray(d["U"])
        if U.ndim == 1 and U.size % 3 == 0:
            U = U.reshape(-1, 3)
        if U.ndim == 2 and U.shape[1] == 3:
            return np.linalg.norm(U, axis=1), r"$|U|$ [m/s]"
    if "p" in d:
        return np.asarray(d["p"]).ravel(), r"$p/\rho$ [m$^2$/s$^2$]"
    n = len(data["points"])
    return np.zeros(n), "empty"


def _prefer_side_cut(tdir: Path) -> str:
    """Prefer a longitudinal cut (through-flow plane) over a cross-cut."""
    # cutB is typically z-normal → shows (x,y) with y = shaft/advance axis
    for name in ("cutB", "cutA", "yNormal", "zNormal", "rotor"):
        if (tdir / f"{name}.vtk").is_file():
            return name
    v = list(tdir.glob("*.vtk"))
    if not v:
        raise SystemExit(f"No VTK surfaces in {tdir}")
    return v[0].stem


def _flow_plane_coords(pts: np.ndarray, U):
    """
    Map 3D cut to 2D with flow left→right.

    Pumpjet convention: freestream U≈(0,-Va,0) so fluid moves +y → −y.
    Plot horizontal s = −y (upstream left, downstream right) and vertical
    the remaining in-plane coordinate with largest variance.
    """
    # Drop nearly-constant coordinate (cut-plane normal)
    var = pts.var(axis=0)
    drop = int(np.argmin(var))
    keep = [i for i in range(3) if i != drop]
    # Prefer y as the streamwise axis when present
    if 1 in keep:
        stream_i = 1
        span_i = keep[0] if keep[0] != 1 else keep[1]
    else:
        # fall back: largest variance among keep as streamwise
        stream_i = keep[int(np.argmax(var[keep]))]
        span_i = keep[0] if keep[0] != stream_i else keep[1]

    # Horizontal: −y so flow (negative Uy freestream) goes left→right
    s = -pts[:, stream_i]
    n = pts[:, span_i]
    xy = np.column_stack([s, n])

    u_s = u_n = None
    if U is not None and U.ndim == 2 and U.shape[1] == 3:
        # d(s)/dt with s=−y → u_s = −Uy ; span component as-is
        u_s = -U[:, stream_i]
        u_n = U[:, span_i]
    names = (f"streamwise (−y) [m]", f"{'xyz'[span_i]} [m]")
    return xy, u_s, u_n, names, stream_i, span_i


def main():
    case = Path(os.environ.get("CASE_DIR", ".")).resolve()
    surf = case / "postProcessing" / "surfaces"
    if not surf.is_dir():
        raise SystemExit(f"No surfaces at {surf}")

    times = list_times(surf)
    if len(times) < 2:
        raise SystemExit(f"Need >=2 surface times, found {len(times)}")

    # Prefer full-domain longitudinal cut for left→right through-flow movie
    style = os.environ.get("MOVIE_STYLE", "flow").lower()
    mid = times[len(times) // 2][1]
    if style in ("flow", "flowfield", "through"):
        sample_name = _prefer_side_cut(mid)
    else:
        sample_name = pick_surface(mid)
    print(f"Using surface series: {sample_name}  ({len(times)} times)  style={style}")

    # Validate field parse
    probe = read_legacy_vtk_polydata(mid / f"{sample_name}.vtk")
    print("Field keys:", list(probe["data"].keys()), "pts", probe["points"].shape)
    sc0, label = scalar_from_data(probe)
    print(f"scalar {label}: min={sc0.min():.4g} max={sc0.max():.4g} mean={sc0.mean():.4g}")
    if sc0.max() - sc0.min() < 1e-12:
        for alt in ("cutB", "cutA", "rotor"):
            fp = mid / f"{alt}.vtk"
            if fp.is_file() and alt != sample_name:
                probe = read_legacy_vtk_polydata(fp)
                sc0, label = scalar_from_data(probe)
                print(f"alt {alt} keys={list(probe['data'].keys())} range={sc0.min():.4g}..{sc0.max():.4g}")
                if sc0.max() - sc0.min() > 1e-12:
                    sample_name = alt
                    break

    frames_dir = case / "movies" / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("frame_*.png"):
        old.unlink()

    # Color limits from several samples (avoid startup-only range)
    samples = []
    u_ax_samples = []
    for idx in [0, len(times) // 4, len(times) // 2, 3 * len(times) // 4, -1]:
        fp = times[idx][1] / f"{sample_name}.vtk"
        if not fp.is_file():
            continue
        d = read_legacy_vtk_polydata(fp)
        sc, _ = scalar_from_data(d)
        samples.append(sc)
        U = d["data"].get("U")
        if U is not None:
            U = np.asarray(U)
            if U.ndim == 1:
                U = U.reshape(-1, 3)
            # axial freestream component Uy (flow is −y)
            u_ax_samples.append(-U[:, 1])
    allsc = np.concatenate(samples) if samples else sc0
    vmin, vmax = np.percentile(allsc, [2, 98])
    if not np.isfinite(vmin) or not np.isfinite(vmax) or vmax <= vmin:
        vmin, vmax = float(np.min(allsc)), float(np.max(allsc) + 1e-6)
    # Streamwise speed color band for distinct jet vs freestream
    if u_ax_samples:
        ua = np.concatenate(u_ax_samples)
        ua_lo, ua_hi = np.percentile(ua, [2, 98])
    else:
        ua_lo, ua_hi = vmin, vmax

    def body_outline(tdir: Path):
        pts_list = []
        for name in ("rotor", "stator0", "stator"):
            fp = tdir / f"{name}.vtk"
            if not fp.is_file():
                # try glob
                for g in tdir.glob(f"{name}*.vtk"):
                    fp = g
                    break
                else:
                    continue
            try:
                rd = read_legacy_vtk_polydata(fp)
                pts_list.append(rd["points"])
            except Exception:
                pass
        if not pts_list:
            return None
        return np.vstack(pts_list)

    w = int(os.environ.get("MOVIE_WIDTH", 1280))
    h = int(os.environ.get("MOVIE_HEIGHT", 720))
    dpi = 100
    fig_w, fig_h = w / dpi, h / dpi
    show_quiver = os.environ.get("MOVIE_QUIVER", "1") not in ("0", "false", "no")

    for fi, (tval, tdir) in enumerate(times):
        fpath = tdir / f"{sample_name}.vtk"
        data = read_legacy_vtk_polydata(fpath)
        pts = data["points"]
        tris = data["tris"]
        U = data["data"].get("U")
        if U is not None:
            U = np.asarray(U)
            if U.ndim == 1:
                U = U.reshape(-1, 3)

        xy, u_s, u_n, axis_labels, stream_i, span_i = _flow_plane_coords(pts, U)

        # Color by streamwise speed (distinct freestream → acceleration through jet)
        if u_s is not None:
            scalar = u_s
            label = r"streamwise speed $u_s=-U_y$ [m/s]"
            cmin, cmax = ua_lo, ua_hi
        else:
            scalar, label = scalar_from_data(data)
            cmin, cmax = vmin, vmax

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        fig.patch.set_facecolor("#070b10")
        ax.set_facecolor("#0c121a")

        if len(tris) > 0 and tris.max() < len(pts):
            tri = Triangulation(xy[:, 0], xy[:, 1], tris)
            tcf = ax.tripcolor(
                tri, scalar, shading="gouraud", cmap="turbo", vmin=cmin, vmax=cmax
            )
            # Contours make acceleration through the duct more distinct
            try:
                ax.tricontour(
                    tri,
                    scalar,
                    levels=12,
                    colors="white",
                    linewidths=0.35,
                    alpha=0.35,
                )
            except Exception:
                pass
        else:
            tcf = ax.scatter(
                xy[:, 0], xy[:, 1], c=scalar, s=6, cmap="turbo", vmin=cmin, vmax=cmax
            )

        # Velocity arrows (subsampled) — show left→right motion through/around unit
        if show_quiver and u_s is not None and u_n is not None and len(xy) > 20:
            rng = np.random.default_rng(0)
            nq = min(450, len(xy))
            # Prefer points across the full streamwise extent
            order = np.argsort(xy[:, 0])
            stride = max(1, len(order) // nq)
            idx = order[::stride][:nq]
            # Fixed-scale arrows so freestream and jet both readable
            speed = np.hypot(u_s[idx], u_n[idx]) + 1e-12
            scale_ref = max(float(np.percentile(speed, 90)), 1e-6)
            ax.quiver(
                xy[idx, 0],
                xy[idx, 1],
                u_s[idx] / scale_ref,
                u_n[idx] / scale_ref,
                color="white",
                alpha=0.75,
                scale=28,
                width=0.0022,
                headwidth=3.5,
                headlength=4.0,
                pivot="mid",
                zorder=6,
            )

        # Body overlay
        bp = body_outline(tdir)
        if bp is not None and len(bp):
            bxy, _, _, _, _, _ = _flow_plane_coords(bp, None)
            ax.scatter(bxy[:, 0], bxy[:, 1], s=1.2, c="#101010", alpha=0.7, zorder=5)

        # Annotate inlet / pumpjet / wake
        smin, smax = float(xy[:, 0].min()), float(xy[:, 0].max())
        nmin, nmax = float(xy[:, 1].min()), float(xy[:, 1].max())
        y_ann = nmax - 0.04 * (nmax - nmin + 1e-12)
        for xpos, txt in (
            (smin + 0.08 * (smax - smin), "INLET →"),
            (0.5 * (smin + smax), "PUMPJET"),
            (smax - 0.12 * (smax - smin), "→ WAKE"),
        ):
            ax.text(
                xpos,
                y_ann,
                txt,
                color="#e8f0ff",
                fontsize=11,
                ha="center",
                va="top",
                fontweight="bold",
                alpha=0.9,
                zorder=8,
            )

        cb = fig.colorbar(tcf, ax=ax, fraction=0.035, pad=0.02)
        cb.set_label(label, color="white")
        cb.ax.yaxis.set_tick_params(color="white")
        plt.setp(plt.getp(cb.ax.axes, "yticklabels"), color="white")

        ax.set_aspect("equal", adjustable="box")
        ax.set_title(
            f"Pumpjet V3 MRF — through-flow ({sample_name})   t = {tval:.5g} s",
            color="white",
            fontsize=13,
        )
        ax.set_xlabel(f"{axis_labels[0]}   (flow left → right)", color="white")
        ax.set_ylabel(axis_labels[1], color="white")
        ax.tick_params(colors="white")
        for spine in ax.spines.values():
            spine.set_color("#445566")
        fig.tight_layout()
        fig.savefig(frames_dir / f"frame_{fi:04d}.png", dpi=dpi, facecolor=fig.get_facecolor())
        plt.close(fig)
        if fi % 10 == 0:
            print(
                f"frame {fi}/{len(times)} t={tval}  "
                f"srange={scalar.min():.3g}..{scalar.max():.3g}"
            )

    n = len(list(frames_dir.glob("frame_*.png")))
    print("frames", n)
    if n < 2:
        raise SystemExit("Not enough frames")

    fps = float(os.environ.get("MOVIE_FPS", 12))
    dur = float(os.environ.get("MOVIE_DURATION_SEC", 10))
    play_fps = max(1.0, n / dur)
    mp4 = case / "movies" / "propulsor_flow.mp4"
    subprocess.check_call(
        [
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
            "18",
            "-movflags",
            "+faststart",
            "-t",
            str(dur),
            str(mp4),
        ]
    )
    print("Wrote", mp4, f"({play_fps:.2f} fps playback, {dur}s)")
    (case / f"propulsor_flow_{int(dur)}s.mp4").write_bytes(mp4.read_bytes())


if __name__ == "__main__":
    main()

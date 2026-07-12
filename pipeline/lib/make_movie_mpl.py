#!/usr/bin/env python3
"""
Fallback movie generator using matplotlib (no ParaView/OpenGL).

Reads OpenFOAM surface function-object legacy VTK polydata (BINARY FIELD
attributes format) and builds an MP4 via ffmpeg.
"""
from __future__ import annotations

import os
import re
import struct
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.tri import Triangulation
from matplotlib.patches import FancyBboxPatch


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


def _prefer_meridional_cut(tdir: Path) -> str:
    """
    Prefer a *meridional* cut (plane containing the shaft axis) for side view.

    For axis ∥ y: cut with normal ∥ z (or x) shows the long through-flow plane.
    Pick the cut whose points span the *largest streamwise (y) extent*.
    """
    candidates = []
    for name in ("cutA", "cutB", "cutMeridional", "yNormal", "zNormal", "xNormal"):
        fp = tdir / f"{name}.vtk"
        if not fp.is_file():
            continue
        try:
            pts = read_legacy_vtk_polydata(fp)["points"]
        except Exception:
            continue
        # y-extent (shaft/advance axis)
        y_span = float(pts[:, 1].max() - pts[:, 1].min())
        # face-on cuts have tiny y span; meridional cuts have large y span
        candidates.append((y_span, name))
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    v = list(tdir.glob("*.vtk"))
    if not v:
        raise SystemExit(f"No VTK surfaces in {tdir}")
    return v[0].stem


def _meridional_coords(pts: np.ndarray, U=None, axis_i: int = 1):
    """
    Project a cut (or body points near a cut) to 2D meridional coordinates.

    Horizontal s = −axis_coord so freestream U=(0,−Va,0) flows left→right.
    Vertical = the in-plane radial-ish coordinate (largest variance among non-axis).
    """
    # Drop the nearly-constant normal direction of a cut plane
    var = pts.var(axis=0)
    drop = int(np.argmin(var))
    keep = [i for i in range(3) if i != drop]

    if axis_i in keep:
        stream_i = axis_i
        span_i = keep[0] if keep[0] != axis_i else keep[1]
    else:
        # body cloud may not be flat — force axis as streamwise, pick span by variance
        stream_i = axis_i
        others = [i for i in range(3) if i != axis_i]
        span_i = others[int(np.argmax(var[others]))]

    # Left = upstream (+y for our freestream), right = downstream (−y)
    s = -pts[:, stream_i]
    n = pts[:, span_i]
    xy = np.column_stack([s, n])

    u_s = u_n = None
    if U is not None:
        U = np.asarray(U)
        if U.ndim == 1:
            U = U.reshape(-1, 3)
        if U.ndim == 2 and U.shape[1] == 3:
            u_s = -U[:, stream_i]
            u_n = U[:, span_i]

    names = (
        f"streamwise (−{'xyz'[stream_i]}) [m]",
        f"{'xyz'[span_i]} [m]",
    )
    return xy, u_s, u_n, names, stream_i, span_i, drop


def _read_binary_stl_tris(path: Path) -> np.ndarray:
    """Return (n, 3, 3) triangle vertex array from a binary STL."""
    raw = Path(path).read_bytes()
    if len(raw) < 84:
        raise ValueError(f"STL too small: {path}")
    n = struct.unpack_from("<I", raw, 80)[0]
    need = 84 + n * 50
    if len(raw) < need:
        # ASCII or truncated — try naive ASCII parse
        return _read_ascii_stl_tris(path)
    tris = np.empty((n, 3, 3), dtype=np.float64)
    off = 84
    for i in range(n):
        # skip normal (3 floats), read 9 vertex floats
        vals = struct.unpack_from("<12f", raw, off)
        tris[i, 0] = vals[3:6]
        tris[i, 1] = vals[6:9]
        tris[i, 2] = vals[9:12]
        off += 50
    return tris


def _read_ascii_stl_tris(path: Path) -> np.ndarray:
    text = Path(path).read_text(errors="ignore")
    verts = []
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("vertex"):
            parts = line.split()
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
    arr = np.asarray(verts, dtype=np.float64).reshape(-1, 3, 3)
    return arr


def _plane_tri_segments(
    tris: np.ndarray,
    normal_i: int,
    plane: float = 0.0,
) -> np.ndarray:
    """
    Intersect triangles with plane x[normal_i] = plane.
    Returns (m, 2, 3) line segments in 3D.
    """
    segs = []
    for tri in tris:
        d = tri[:, normal_i] - plane
        # collect edge intersection points
        pts = []
        for a, b in ((0, 1), (1, 2), (2, 0)):
            da, db = d[a], d[b]
            if abs(da) < 1e-14 and abs(db) < 1e-14:
                # edge on plane — take both endpoints
                pts.append(tri[a])
                pts.append(tri[b])
            elif da * db < 0:
                t = da / (da - db)
                pts.append(tri[a] + t * (tri[b] - tri[a]))
            elif abs(da) < 1e-14:
                pts.append(tri[a])
            elif abs(db) < 1e-14:
                pts.append(tri[b])
        if len(pts) < 2:
            continue
        # unique points
        P = np.asarray(pts, dtype=np.float64)
        # keep first two sufficiently distinct points
        used = [0]
        for i in range(1, len(P)):
            if np.linalg.norm(P[i] - P[used[0]]) > 1e-10:
                used.append(i)
                break
        if len(used) < 2:
            continue
        segs.append([P[used[0]], P[used[1]]])
    if not segs:
        return np.zeros((0, 2, 3))
    return np.asarray(segs, dtype=np.float64)


def _seg_to_meridional(segs: np.ndarray, stream_i: int, span_i: int) -> np.ndarray:
    """Map 3D segments to 2D (s, span) with s = −stream for L→R flow."""
    if len(segs) == 0:
        return np.zeros((0, 2, 2))
    out = np.empty((len(segs), 2, 2), dtype=np.float64)
    out[:, :, 0] = -segs[:, :, stream_i]
    out[:, :, 1] = segs[:, :, span_i]
    return out


def _find_geometry_stls(case: Path) -> List[Path]:
    """Locate rotor/stator STLs for clean section outlines (case first only)."""
    found: List[Path] = []
    names = ("rotor.stl", "stator0.stl", "duct_stator.stl", "stator.stl")
    # 1) Explicit env paths (pipeline config) — preferred single source
    for key in ("ROTOR_STL", "STATOR_STLS"):
        v = os.environ.get(key, "").strip().strip('"')
        if not v:
            continue
        for part in v.split():
            p = Path(part)
            if p.is_file():
                found.append(p)
    # 2) Case geometry only if no env STLs given
    if not found:
        for d in (case / "constant" / "geometry", case / "constant" / "triSurface"):
            if not d.is_dir():
                continue
            for name in names:
                p = d / name
                if p.is_file():
                    found.append(p)
    # 3) Fallback: design/geometry_v3
    if not found:
        for d in (
            case.parent.parent / "design" / "geometry_v3",
            case.parent.parent / "design" / "geometry",
        ):
            if not d.is_dir():
                continue
            for name in names:
                p = d / name
                if p.is_file():
                    found.append(p)
    uniq = []
    seen = set()
    for p in found:
        r = str(p.resolve())
        if r not in seen:
            seen.add(r)
            uniq.append(p)
    return uniq


def _stl_meridional_sections(
    stl_paths: List[Path],
    stream_i: int,
    span_i: int,
    normal_i: int,
    plane: float = 0.0,
) -> List[Tuple[str, np.ndarray]]:
    """Return list of (label, segments_2d) for each STL."""
    out = []
    for p in stl_paths:
        try:
            tris = _read_binary_stl_tris(p)
            segs3 = _plane_tri_segments(tris, normal_i, plane)
            segs2 = _seg_to_meridional(segs3, stream_i, span_i)
            if len(segs2):
                label = p.stem
                out.append((label, segs2))
                print(f"  STL section {p.name}: {len(segs2)} segments")
        except Exception as e:
            print(f"  STL section skip {p}: {e}")
    return out


def _draw_sections(ax, sections: List[Tuple[str, np.ndarray]], zorder: int = 6):
    """Draw CAD section linework (fallback). Prefer _draw_engineering_outline."""
    style = {
        "rotor": dict(color="#0d0d0d", lw=1.0, alpha=0.95),
        "stator0": dict(color="#1a1a1a", lw=0.9, alpha=0.9),
        "duct_stator": dict(color="#1a1a1a", lw=0.9, alpha=0.9),
        "stator": dict(color="#1a1a1a", lw=0.9, alpha=0.9),
    }
    for label, segs in sections:
        st = style.get(label, dict(color="#000000", lw=0.9, alpha=0.9))
        for seg in segs:
            ax.plot(seg[:, 0], seg[:, 1], solid_capstyle="round", zorder=zorder, **st)


def _load_design_params(case: Path) -> dict:
    for p in (
        case.parent.parent / "design" / "geometry_v3" / "design_params.json",
        case / "pipeline_meta.json",
    ):
        if p.is_file():
            try:
                import json

                return json.loads(p.read_text())
            except Exception:
                pass
    return {}


def _engineering_outline_polys(case: Path, stream_i: int = 1) -> List[dict]:
    """
    Build clean filled meridional solid regions for a pumpjet side view.

    Coordinate system matches the movie: s = −y (flow L→R), radial = x.
    Solids: hub cylinder section, upper/lower duct wall sections (annulus ∩ z=0).
    Dimensions from design_params + STL axial extents only (not full blade radius).
    """
    # Defaults: generate_pumpjet_v3 moderate-load
    D = 0.20
    hub_r = 0.030
    tip_clear = 0.004
    R = 0.5 * D
    y_hub0, y_hub1 = -0.018, 0.030
    y_duct0, y_duct1 = -0.055, 0.11
    wall = 0.012  # duct wall thickness

    meta = _load_design_params(case)
    if meta:
        D = float(meta.get("D", D))
        R = 0.5 * D
        if "hub_ratio" in meta:
            hub_r = float(meta["hub_ratio"]) * R  # hub_ratio = 2*hub_r/D → hub_r = ratio*R
            # design stores hub_ratio = 2*hub_r/D = hub_r/R
            hub_r = float(meta["hub_ratio"]) * R
        if "tip_clearance_m" in meta:
            tip_clear = float(meta["tip_clearance_m"])

    # Axial extents from STL bboxes (reliable); radii from design (not blade tips)
    stls = _find_geometry_stls(case)
    for p in stls:
        try:
            tris = _read_binary_stl_tris(p)
            mn = tris.reshape(-1, 3).min(0)
            mx = tris.reshape(-1, 3).max(0)
            name = p.stem.lower()
            if "rotor" in name:
                y_hub0, y_hub1 = float(mn[1]), float(mx[1])
            if "stator" in name or "duct" in name:
                y_duct0, y_duct1 = float(mn[1]), float(mx[1])
        except Exception:
            pass

    r_tip = R - tip_clear
    r_in = R + 0.0015  # bore slightly above tip
    r_out = r_in + wall

    # s = −y  (ensure s0 < s1)
    s0_h, s1_h = sorted((-y_hub1, -y_hub0))
    s0_d, s1_d = sorted((-y_duct1, -y_duct0))

    polys = [
        {
            "name": "hub",
            "xy": np.array(
                [[s0_h, -hub_r], [s1_h, -hub_r], [s1_h, hub_r], [s0_h, hub_r]]
            ),
            "facecolor": "#2c2c32",
            "edgecolor": "#f2f2f6",
            "lw": 1.3,
            "alpha": 0.95,
        },
        {
            "name": "duct_upper",
            "xy": np.array(
                [[s0_d, r_in], [s1_d, r_in], [s1_d, r_out], [s0_d, r_out]]
            ),
            "facecolor": "#4a4a54",
            "edgecolor": "#f2f2f6",
            "lw": 1.2,
            "alpha": 0.93,
        },
        {
            "name": "duct_lower",
            "xy": np.array(
                [[s0_d, -r_out], [s1_d, -r_out], [s1_d, -r_in], [s0_d, -r_in]]
            ),
            "facecolor": "#4a4a54",
            "edgecolor": "#f2f2f6",
            "lw": 1.2,
            "alpha": 0.93,
        },
    ]
    # Rotor plane marker (blade disk)
    s_rotor = 0.5 * (s0_h + s1_h)
    polys.append(
        {
            "name": "rotor_disk_guide",
            "type": "vlines",
            "s": s_rotor,
            "x0": -r_tip,
            "x1": r_tip,
        }
    )
    return polys


def _draw_engineering_outline(
    ax,
    case: Path,
    sections: List[Tuple[str, np.ndarray]],
    zorder: int = 7,
):
    """Filled hub + duct walls + fine STL blade/cut linework."""
    from matplotlib.patches import Polygon

    for poly in _engineering_outline_polys(case):
        if poly.get("type") == "vlines":
            ax.plot(
                [poly["s"], poly["s"]],
                [poly["x0"], poly["x1"]],
                color="#ffdd88",
                ls="--",
                lw=0.9,
                alpha=0.75,
                zorder=zorder + 1,
            )
            continue
        patch = Polygon(
            poly["xy"],
            closed=True,
            facecolor=poly["facecolor"],
            edgecolor=poly["edgecolor"],
            linewidth=poly["lw"],
            alpha=poly["alpha"],
            zorder=zorder,
            joinstyle="round",
        )
        ax.add_patch(patch)

    # Blade cuts only: STL segments with mid-radius between hub and duct bore
    hub_r_est = 0.03
    r_bore = 0.10
    for label, segs in sections:
        if "rotor" not in label.lower():
            continue
        for seg in segs:
            rmid = 0.5 * (abs(seg[0, 1]) + abs(seg[1, 1]))
            if rmid < hub_r_est * 1.15 or rmid > r_bore * 0.98:
                continue  # skip hub skin / outer tips clutter
            ax.plot(
                seg[:, 0],
                seg[:, 1],
                color="#ffe0a0",
                lw=1.0,
                alpha=0.9,
                solid_capstyle="round",
                zorder=zorder + 2,
            )

    ax.text(
        0.0,
        0.0,
        "hub",
        color="#ffffff",
        fontsize=7,
        ha="center",
        va="center",
        zorder=zorder + 3,
        alpha=0.95,
        fontweight="bold",
    )
    # duct labels in main axes only if wide enough
    ax.text(
        0.0,
        0.11,
        "duct",
        color="#dde0e8",
        fontsize=6.5,
        ha="center",
        va="bottom",
        zorder=zorder + 3,
        alpha=0.85,
    )


def main():
    case = Path(os.environ.get("CASE_DIR", ".")).resolve()
    surf = case / "postProcessing" / "surfaces"
    if not surf.is_dir():
        raise SystemExit(f"No surfaces at {surf}")

    times = list_times(surf)
    if len(times) < 2:
        raise SystemExit(f"Need >=2 surface times, found {len(times)}")

    # Prefer full-domain *meridional* cut (side view through shaft), not face-on
    style = os.environ.get("MOVIE_STYLE", "flow").lower()
    mid = times[len(times) // 2][1]
    if style in ("flow", "flowfield", "through"):
        sample_name = _prefer_meridional_cut(mid)
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

    w = int(os.environ.get("MOVIE_WIDTH", 1280))
    h = int(os.environ.get("MOVIE_HEIGHT", 720))
    dpi = 100
    fig_w, fig_h = w / dpi, h / dpi
    show_quiver = os.environ.get("MOVIE_QUIVER", "0") in ("1", "true", "yes")
    # Shaft / advance axis index (y=1 for this pumpjet pipeline)
    axis_i = int(os.environ.get("MOVIE_AXIS_INDEX", "1"))
    # Engineering layout: full domain + optional zoom inset on the unit
    show_inset = os.environ.get("MOVIE_INSET", "1") in ("1", "true", "yes")

    # Probe first frame for axis mapping, then build CAD sections once
    d0 = read_legacy_vtk_polydata(times[0][1] / f"{sample_name}.vtk")
    U0 = d0["data"].get("U")
    if U0 is not None:
        U0 = np.asarray(U0).reshape(-1, 3)
    _, _, _, axis_labels, stream_i, span_i, normal_i = _meridional_coords(
        d0["points"], U0, axis_i=axis_i
    )
    print(
        f"Meridional map: stream={'xyz'[stream_i]}  span={'xyz'[span_i]}  "
        f"normal={'xyz'[normal_i]}  (flow left→right)"
    )
    stl_paths = _find_geometry_stls(case)
    print("Geometry STLs for section:", [str(p) for p in stl_paths])
    sections = _stl_meridional_sections(stl_paths, stream_i, span_i, normal_i, plane=0.0)
    if not sections:
        print("WARNING: no STL sections — pumpjet outline will be missing")

    # Zoom box around geometry from STL segments
    if sections:
        all_s = np.concatenate([sg[:, :, 0].ravel() for _, sg in sections])
        all_n = np.concatenate([sg[:, :, 1].ravel() for _, sg in sections])
        pad_s = 0.08
        pad_n = 0.04
        zoom = (
            float(all_s.min()) - pad_s,
            float(all_s.max()) + pad_s,
            float(all_n.min()) - pad_n,
            float(all_n.max()) + pad_n,
        )
    else:
        zoom = (-0.25, 0.25, -0.18, 0.18)

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

        xy, u_s, u_n, axis_labels, stream_i, span_i, normal_i = _meridional_coords(
            pts, U, axis_i=axis_i
        )

        # Color by streamwise speed
        if u_s is not None:
            scalar = u_s
            label = r"streamwise speed $u_s=-U_y$  [m/s]"
            cmin, cmax = ua_lo, ua_hi
        else:
            scalar, label = scalar_from_data(data)
            cmin, cmax = vmin, vmax

        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        fig.patch.set_facecolor("#0b1018")
        ax.set_facecolor("#101820")

        if len(tris) > 0 and tris.max() < len(pts):
            tri = Triangulation(xy[:, 0], xy[:, 1], tris)
            tcf = ax.tripcolor(
                tri, scalar, shading="gouraud", cmap="turbo", vmin=cmin, vmax=cmax
            )
            try:
                ax.tricontour(
                    tri,
                    scalar,
                    levels=14,
                    colors="white",
                    linewidths=0.28,
                    alpha=0.28,
                )
            except Exception:
                pass
        else:
            tcf = ax.scatter(
                xy[:, 0], xy[:, 1], c=scalar, s=6, cmap="turbo", vmin=cmin, vmax=cmax
            )

        # Engineering meridional outline: filled hub + duct walls + blade cuts
        _draw_engineering_outline(ax, case, sections, zorder=7)

        # Shaft centreline
        smin, smax = float(xy[:, 0].min()), float(xy[:, 0].max())
        nmin, nmax = float(xy[:, 1].min()), float(xy[:, 1].max())
        ax.axhline(0.0, color="#8899aa", ls="--", lw=0.6, alpha=0.55, zorder=4)

        if show_quiver and u_s is not None and u_n is not None and len(xy) > 20:
            nq = min(350, len(xy))
            order = np.argsort(xy[:, 0])
            stride = max(1, len(order) // nq)
            idx = order[::stride][:nq]
            speed = np.hypot(u_s[idx], u_n[idx]) + 1e-12
            scale_ref = max(float(np.percentile(speed, 90)), 1e-6)
            ax.quiver(
                xy[idx, 0],
                xy[idx, 1],
                u_s[idx] / scale_ref,
                u_n[idx] / scale_ref,
                color="white",
                alpha=0.55,
                scale=32,
                width=0.0018,
                headwidth=3.2,
                headlength=3.5,
                pivot="mid",
                zorder=5,
            )

        y_ann = nmax - 0.05 * (nmax - nmin + 1e-12)
        for xpos, txt in (
            (smin + 0.10 * (smax - smin), "INLET  →"),
            (0.5 * (smin + smax), "PUMPJET"),
            (smax - 0.12 * (smax - smin), "→  WAKE / JET"),
        ):
            ax.text(
                xpos,
                y_ann,
                txt,
                color="#f0f4ff",
                fontsize=11,
                ha="center",
                va="top",
                fontweight="bold",
                alpha=0.95,
                zorder=9,
                bbox=dict(
                    boxstyle="round,pad=0.25",
                    facecolor="#0b1018",
                    edgecolor="#445566",
                    alpha=0.75,
                ),
            )

        # Rectangle marking the unit for the team
        if sections:
            ax.add_patch(
                plt.Rectangle(
                    (zoom[0], zoom[2]),
                    zoom[1] - zoom[0],
                    zoom[3] - zoom[2],
                    fill=False,
                    edgecolor="#ffcc66",
                    lw=1.0,
                    ls=":",
                    alpha=0.7,
                    zorder=8,
                )
            )

        cb = fig.colorbar(tcf, ax=ax, fraction=0.032, pad=0.02)
        cb.set_label(label, color="white", fontsize=10)
        cb.ax.yaxis.set_tick_params(color="white")
        plt.setp(plt.getp(cb.ax.axes, "yticklabels"), color="white")

        ax.set_aspect("equal", adjustable="box")
        ax.set_title(
            f"Pumpjet V3 — meridional section through shaft  |  t = {tval:.5g} s  |  MRF, 6-proc",
            color="white",
            fontsize=12,
            pad=10,
        )
        ax.set_xlabel(
            r"streamwise $s=-y$ [m]   (freestream left $\rightarrow$ jet right)",
            color="white",
            fontsize=10,
        )
        ax.set_ylabel(r"radial $x$ [m]   (shaft on $x=0$)", color="white", fontsize=10)
        ax.tick_params(colors="white", labelsize=9)
        for spine in ax.spines.values():
            spine.set_color("#556677")

        # Inset: zoom on pumpjet with same field + CAD section
        if show_inset and sections:
            from mpl_toolkits.axes_grid1.inset_locator import inset_axes

            axins = inset_axes(ax, width="38%", height="48%", loc="lower left", borderpad=1.2)
            axins.set_facecolor("#101820")
            if len(tris) > 0 and tris.max() < len(pts):
                axins.tripcolor(
                    tri, scalar, shading="gouraud", cmap="turbo", vmin=cmin, vmax=cmax
                )
            _draw_engineering_outline(axins, case, sections, zorder=7)
            axins.axhline(0.0, color="#8899aa", ls="--", lw=0.5, alpha=0.5)
            axins.set_xlim(zoom[0], zoom[1])
            axins.set_ylim(zoom[2], zoom[3])
            axins.set_aspect("equal", adjustable="box")
            axins.set_title("detail", color="#ffcc66", fontsize=9, pad=2)
            axins.tick_params(colors="white", labelsize=7)
            for spine in axins.spines.values():
                spine.set_color("#ffcc66")
                spine.set_linewidth(1.2)

        try:
            fig.tight_layout()
        except Exception:
            pass
        fig.savefig(
            frames_dir / f"frame_{fi:04d}.png",
            dpi=dpi,
            facecolor=fig.get_facecolor(),
            bbox_inches="tight",
            pad_inches=0.15,
        )
        plt.close(fig)
        if fi % 10 == 0:
            print(
                f"frame {fi}/{len(times)} t={tval}  "
                f"srange={float(np.min(scalar)):.3g}..{float(np.max(scalar)):.3g}  "
                f"stream={'xyz'[stream_i]} span={'xyz'[span_i]}"
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

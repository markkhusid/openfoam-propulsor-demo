#!/usr/bin/env python3
"""STL helpers: bounding box, scale, basic watertight checks, domain sizing."""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import numpy as np


Vec3 = Tuple[float, float, float]


@dataclass
class StlMesh:
    path: Path
    vertices: np.ndarray  # (N, 3) unique-ish sample of triangle verts
    n_triangles: int
    binary: bool


def _parse_ascii_stl(data: str) -> np.ndarray:
    verts: List[List[float]] = []
    for line in data.splitlines():
        line = line.strip()
        if line.lower().startswith("vertex"):
            parts = line.split()
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
    if not verts:
        raise ValueError("No vertices found in ASCII STL")
    return np.asarray(verts, dtype=float)


def _parse_binary_stl(raw: bytes) -> np.ndarray:
    if len(raw) < 84:
        raise ValueError("Binary STL too small")
    n_tri = struct.unpack_from("<I", raw, 80)[0]
    expected = 84 + n_tri * 50
    if len(raw) < expected:
        raise ValueError(f"Binary STL truncated: got {len(raw)} expected ~{expected}")
    verts = np.empty((n_tri * 3, 3), dtype=np.float64)
    off = 84
    for i in range(n_tri):
        # normal (12) + 3 verts (36) + attr (2)
        v = struct.unpack_from("<12x9fH", raw, off)
        verts[i * 3 + 0] = v[0:3]
        verts[i * 3 + 1] = v[3:6]
        verts[i * 3 + 2] = v[6:9]
        off += 50
    return verts


def load_stl(path: Path) -> StlMesh:
    path = Path(path)
    raw = path.read_bytes()
    binary = True
    try:
        head = raw[:80].decode("ascii", errors="ignore").lower()
        if "solid" in head and b"\x00" not in raw[:100]:
            # might be ascii
            text = raw.decode("utf-8", errors="ignore")
            if "facet" in text.lower():
                verts = _parse_ascii_stl(text)
                n_tri = len(verts) // 3
                return StlMesh(path, verts, n_tri, binary=False)
    except Exception:
        pass
    verts = _parse_binary_stl(raw)
    return StlMesh(path, verts, len(verts) // 3, binary=True)


def bbox(verts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    return verts.min(axis=0), verts.max(axis=0)


def scale_stl(in_path: Path, out_path: Path, scale: float) -> StlMesh:
    """Rewrite STL scaled about origin (binary out)."""
    mesh = load_stl(in_path)
    v = mesh.vertices * float(scale)
    n_tri = mesh.n_triangles
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Rebuild triangles from flat vertex list
    header = b"scaled by propulsor pipeline" + b"\0" * 80
    header = header[:80]
    body = bytearray()
    body += header
    body += struct.pack("<I", n_tri)
    for i in range(n_tri):
        p0, p1, p2 = v[i * 3], v[i * 3 + 1], v[i * 3 + 2]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn > 0:
            n = n / nn
        else:
            n = np.array([0.0, 0.0, 1.0])
        body += struct.pack("<3f", *n)
        body += struct.pack("<3f", *p0)
        body += struct.pack("<3f", *p1)
        body += struct.pack("<3f", *p2)
        body += struct.pack("<H", 0)
    out_path.write_bytes(bytes(body))
    return StlMesh(out_path, v, n_tri, binary=True)


def edge_key(a: Sequence[float], b: Sequence[float], tol: float = 1e-9):
    ra = tuple(round(float(x) / tol) * tol for x in a)
    rb = tuple(round(float(x) / tol) * tol for x in b)
    return (ra, rb) if ra <= rb else (rb, ra)


def watertight_report(mesh: StlMesh, sample_tol: float = 1e-7) -> dict:
    """
    Lightweight manifold-edge check (not a full CAD kernel).
    Counts unique edges and how many are shared by != 2 triangles.
    """
    from collections import Counter

    edges: List[tuple] = []
    v = mesh.vertices
    for i in range(mesh.n_triangles):
        p0, p1, p2 = v[i * 3], v[i * 3 + 1], v[i * 3 + 2]
        edges.append(edge_key(p0, p1, sample_tol))
        edges.append(edge_key(p1, p2, sample_tol))
        edges.append(edge_key(p2, p0, sample_tol))
    counts = Counter(edges)
    boundary = sum(1 for c in counts.values() if c == 1)
    nonmanifold = sum(1 for c in counts.values() if c > 2)
    ok = boundary == 0 and nonmanifold == 0
    return {
        "n_triangles": mesh.n_triangles,
        "n_unique_edges": len(counts),
        "boundary_edges": boundary,
        "nonmanifold_edges": nonmanifold,
        "likely_watertight": ok,
    }


def unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n < 1e-15:
        raise ValueError("Zero-length axis vector")
    return v / n


def domain_from_rotor(
    mn: np.ndarray,
    mx: np.ndarray,
    axis: np.ndarray,
    origin: np.ndarray | None,
    up_d: float,
    down_d: float,
    rad_d: float,
    rotzone_r_fac: float,
    rotzone_half_d: float,
    char_diameter: float | None = None,
) -> dict:
    """
    Build a box domain aligned with global axes (snappy-friendly) and a
    rotating cylindrical zone along `axis`.
    """
    axis = unit(np.asarray(axis, dtype=float))
    center = 0.5 * (mn + mx)
    if origin is None:
        origin = center.copy()
    else:
        origin = np.asarray(origin, dtype=float)

    extents = mx - mn
    # Characteristic diameter: max span perpendicular to axis
    # Project bbox corners and take radial extent*2
    corners = np.array(
        [[x, y, z] for x in (mn[0], mx[0]) for y in (mn[1], mx[1]) for z in (mn[2], mx[2])]
    )
    rel = corners - origin
    axial = rel @ axis
    radial_vec = rel - np.outer(axial, axis)
    radial = np.linalg.norm(radial_vec, axis=1)
    r_rotor = float(radial.max())
    length_ax = float(axial.max() - axial.min())
    D = float(char_diameter) if char_diameter else max(2.0 * r_rotor, 1e-6)

    # Domain box (axis-aligned) large enough for cylinder extents
    # Place origin of domain around rotor origin
    # Extent along axis:
    half_up = up_d * D
    half_down = down_d * D
    rad = rad_d * D

    # Build AABB covering cylinder of radius `rad` and axial range
    # For general axis, expand by rad in all cartesian directions (conservative)
    ax_min = origin + axis * (-half_up)
    ax_max = origin + axis * (half_down)
    box_min = np.minimum(ax_min, ax_max) - rad
    box_max = np.maximum(ax_min, ax_max) + rad

    # Also ensure rotor bbox is inside with margin
    box_min = np.minimum(box_min, mn - 0.1 * D)
    box_max = np.maximum(box_max, mx + 0.1 * D)

    rot_r = rotzone_r_fac * r_rotor
    rot_half = rotzone_half_d * D
    p1 = origin - axis * rot_half
    p2 = origin + axis * rot_half

    # locationInMesh: slightly offset from origin along axis
    loc = origin + axis * (0.01 * D) + np.array([1e-4, 1e-4, 1e-4])

    return {
        "D": D,
        "r_rotor": r_rotor,
        "length_axial": length_ax,
        "origin": origin.tolist(),
        "axis": axis.tolist(),
        "box_min": box_min.tolist(),
        "box_max": box_max.tolist(),
        "rot_cylinder": {"point1": p1.tolist(), "point2": p2.tolist(), "radius": rot_r},
        "locationInMesh": loc.tolist(),
    }


def foam_vector(v: Iterable[float]) -> str:
    a = list(v)
    return f"({a[0]} {a[1]} {a[2]})"


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: stl_utils.py <file.stl>")
        sys.exit(2)
    m = load_stl(Path(sys.argv[1]))
    mn, mx = bbox(m.vertices)
    print("triangles", m.n_triangles, "binary", m.binary)
    print("bbox_min", mn)
    print("bbox_max", mx)
    print("report", watertight_report(m))

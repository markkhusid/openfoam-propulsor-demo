#!/usr/bin/env python3
"""
Generate a simplified, mesh-friendly pumpjet (demo).

Design choices (literature-informed, simplified for snappyHexMesh):
  - Rotor: hub + Z blades, P/D ~ 1.05, hub ratio 0.3
  - Duct: thin annular wall, L/D ~ 0.8, mild contraction
  - Stator: post-swirl vanes that stop short of the hub (clearance gap)
  - Also emit rotating-zone / domain helper cylinders as STL for robust NCC
"""
from __future__ import annotations

import json
import math
import struct
from pathlib import Path
from typing import List, Sequence, Tuple

import numpy as np

Vec = np.ndarray
Tri = Tuple[Vec, Vec, Vec]


def nrm(v: Vec) -> Vec:
    n = np.linalg.norm(v)
    return v / n if n > 1e-15 else np.array([0.0, 0.0, 1.0])


def write_binary_stl(path: Path, tris: Sequence[Tri], name: str = "part") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (name.encode("ascii", "ignore")[:80]).ljust(80, b"\0")
    body = bytearray(header)
    body += struct.pack("<I", len(tris))
    for a, b, c in tris:
        nn = nrm(np.cross(b - a, c - a))
        body += struct.pack("<3f", *nn)
        for p in (a, b, c):
            body += struct.pack("<3f", float(p[0]), float(p[1]), float(p[2]))
        body += struct.pack("<H", 0)
    path.write_bytes(bytes(body))
    print(f"Wrote {path} ({len(tris)} tris)")


def add_tri(tris: List[Tri], a, b, c) -> None:
    a, b, c = np.asarray(a, float), np.asarray(b, float), np.asarray(c, float)
    if np.linalg.norm(np.cross(b - a, c - a)) < 1e-16:
        return
    tris.append((a, b, c))


def add_quad(tris: List[Tri], a, b, c, d) -> None:
    add_tri(tris, a, b, c)
    add_tri(tris, a, c, d)


def cylinder_solid(tris, y0, y1, r, n_theta=48):
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    r0 = [np.array([r * math.cos(t), y0, r * math.sin(t)]) for t in th]
    r1 = [np.array([r * math.cos(t), y1, r * math.sin(t)]) for t in th]
    c0, c1 = np.array([0.0, y0, 0.0]), np.array([0.0, y1, 0.0])
    for i in range(n_theta):
        j = (i + 1) % n_theta
        add_quad(tris, r0[i], r0[j], r1[j], r1[i])
        add_tri(tris, c0, r0[j], r0[i])
        add_tri(tris, c1, r1[i], r1[j])


def annular_duct(tris, y0, y1, r_in0, r_out0, r_in1, r_out1, n_theta=64):
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)

    def ring(y, r):
        return [np.array([r * math.cos(t), y, r * math.sin(t)]) for t in th]

    ii0, oo0 = ring(y0, r_in0), ring(y0, r_out0)
    ii1, oo1 = ring(y1, r_in1), ring(y1, r_out1)
    for i in range(n_theta):
        j = (i + 1) % n_theta
        add_quad(tris, oo0[i], oo0[j], oo1[j], oo1[i])  # outer
        add_quad(tris, ii0[j], ii0[i], ii1[i], ii1[j])  # inner
        add_quad(tris, ii0[i], ii0[j], oo0[j], oo0[i])  # inlet annulus
        add_quad(tris, ii1[j], ii1[i], oo1[i], oo1[j])  # outlet annulus


def cylinder_surface_closed(tris, y0, y1, r, n_theta=48, n_y=8):
    """Closed thin shell approximating a cylindrical interface surface (solid tube)."""
    t = 0.0015
    annular_duct(tris, y0, y1, r - t, r + t, r - t, r + t, n_theta=n_theta)


def airfoil(c, t_c=0.12, n=18):
    xs = np.linspace(0, 1, n)
    yt = 5 * t_c * (
        0.2969 * np.sqrt(np.clip(xs, 1e-12, 1))
        - 0.1260 * xs
        - 0.3516 * xs**2
        + 0.2843 * xs**3
        - 0.1015 * xs**4
    )
    upper = np.column_stack([xs * c, yt * c])
    lower = np.column_stack([xs[::-1] * c, -yt[::-1] * c])
    return np.vstack([upper[:-1], lower[:-1]])


def blade(tris, y_le, r_hub, r_tip, ch_h, ch_t, pitch_h, pitch_t, n_span=7, n_sec=14, t_c=0.12):
    spans = np.linspace(0, 1, n_span)
    profs = []
    for s in spans:
        r = r_hub + s * (r_tip - r_hub)
        ch = ch_h + s * (ch_t - ch_h)
        pitch = pitch_h + s * (pitch_t - pitch_h)
        sec = airfoil(ch, t_c, n_sec)
        ca, sa = math.cos(pitch), math.sin(pitch)
        pts = []
        for xc, tc in sec:
            dy = (xc - 0.3 * ch) * ca
            dz = (xc - 0.3 * ch) * sa
            pts.append(np.array([r + tc, y_le + dy, dz]))
        profs.append(np.asarray(pts))
    m = len(profs[0])
    for i in range(n_span - 1):
        for k in range(m):
            k2 = (k + 1) % m
            add_quad(tris, profs[i][k], profs[i][k2], profs[i + 1][k2], profs[i + 1][k])
    root, tip = profs[0], profs[-1]
    rc, tc_ = root.mean(0), tip.mean(0)
    for k in range(m):
        k2 = (k + 1) % m
        add_tri(tris, rc, root[k2], root[k])
        add_tri(tris, tc_, tip[k], tip[k2])


def rot_y(p, ang):
    c, s = math.cos(ang), math.sin(ang)
    return np.array([c * p[0] + s * p[2], p[1], -s * p[0] + c * p[2]])


def rot_tris(tris, ang):
    return [(rot_y(a, ang), rot_y(b, ang), rot_y(c, ang)) for a, b, c in tris]


def generate(out_dir: Path) -> dict:
    D = 0.20
    R = 0.5 * D
    hub_r = 0.03
    tip_clear = 0.004  # 4% R — friendlier for coarse snappy
    r_tip = R - tip_clear
    Zr, Zs = 5, 7
    P_over_D = 1.05

    def pitch_at(r):
        return math.atan(P_over_D * D / (2 * math.pi * max(r, 1e-6)))

    y_rotor = 0.0
    # Rotor
    rotor: List[Tri] = []
    cylinder_solid(rotor, -0.025, 0.04, hub_r, 40)
    for i in range(Zr):
        one: List[Tri] = []
        blade(
            one,
            y_le=-0.005,
            r_hub=hub_r * 1.03,
            r_tip=r_tip,
            ch_h=0.042,
            ch_t=0.028,
            pitch_h=pitch_at(hub_r * 1.15),
            pitch_t=pitch_at(0.7 * R),
            n_span=6,
            n_sec=12,
            t_c=0.13,
        )
        rotor.extend(rot_tris(one, 2 * math.pi * i / Zr))

    # Duct only (no fused hub) — open flow path
    duct: List[Tri] = []
    y_in, y_out = -0.05, 0.11
    annular_duct(
        duct,
        y_in,
        y_out,
        r_in0=R + 0.001,
        r_out0=R + 0.009,
        r_in1=0.92 * R,
        r_out1=0.92 * R + 0.009,
        n_theta=56,
    )
    # Post-swirl stator vanes with hub clearance (do not touch hub)
    for i in range(Zs):
        one = []
        blade(
            one,
            y_le=0.03,
            r_hub=hub_r + 0.012,  # gap to hub
            r_tip=0.90 * R,
            ch_h=0.024,
            ch_t=0.018,
            pitch_h=-0.40,
            pitch_t=-0.28,
            n_span=5,
            n_sec=10,
            t_c=0.11,
        )
        duct.extend(rot_tris(one, 2 * math.pi * i / Zs + math.pi / Zs))

    # Helper surfaces for robust snappy zones (optional use)
    rotzone: List[Tri] = []
    cylinder_surface_closed(rotzone, -0.04, 0.05, r_tip + 0.5 * tip_clear, n_theta=48)

    out_dir = Path(out_dir)
    write_binary_stl(out_dir / "rotor.stl", rotor, "rotor")
    write_binary_stl(out_dir / "duct_stator.stl", duct, "duct_stator")
    write_binary_stl(out_dir / "rotatingZone.stl", rotzone, "rotatingZone")

    meta = {
        "D": D,
        "hub_ratio": 2 * hub_r / D,
        "Zr": Zr,
        "Zs": Zs,
        "pitch_ratio": P_over_D,
        "tip_clearance_m": tip_clear,
        "duct_length_m": y_out - y_in,
        "rpm": 900,
        "Va": 1.5,
        "J": 1.5 / ((900 / 60.0) * D),
        "axis": [0, 1, 0],
        "notes": "Demo pumpjet: simplified blades; not a production naval design.",
    }
    (out_dir / "design_params.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent / "geometry")

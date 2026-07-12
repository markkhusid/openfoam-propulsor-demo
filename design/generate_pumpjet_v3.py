#!/usr/bin/env python3
"""
Pumpjet V3 geometry — moderate loading for T ~ 100–300 N at n ≥ 3000 rpm (water).

Axis: +y shaft. Freestream U = (0, −Va, 0). Thrust reaction on vehicle ≈ +y.

Prior over-pitched design produced KT≈0.65 (T≈3 kN) — far above a 0.2 m
demo unit. This revision uses lighter pitch/chord so open-water KT ~ 0.05–0.1.
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
    a, b, c = map(lambda x: np.asarray(x, float), (a, b, c))
    if np.linalg.norm(np.cross(b - a, c - a)) < 1e-16:
        return
    tris.append((a, b, c))


def add_quad(tris: List[Tri], a, b, c, d) -> None:
    add_tri(tris, a, b, c)
    add_tri(tris, a, c, d)


def cylinder_solid(tris, y0, y1, r, n_theta=56):
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)
    r0 = [np.array([r * math.cos(t), y0, r * math.sin(t)]) for t in th]
    r1 = [np.array([r * math.cos(t), y1, r * math.sin(t)]) for t in th]
    c0, c1 = np.array([0.0, y0, 0.0]), np.array([0.0, y1, 0.0])
    for i in range(n_theta):
        j = (i + 1) % n_theta
        add_quad(tris, r0[i], r0[j], r1[j], r1[i])
        add_tri(tris, c0, r0[j], r0[i])
        add_tri(tris, c1, r1[i], r1[j])


def annular_duct(tris, y0, y1, r_in0, r_out0, r_in1, r_out1, n_theta=96):
    th = np.linspace(0, 2 * np.pi, n_theta, endpoint=False)

    def ring(y, r):
        return [np.array([r * math.cos(t), y, r * math.sin(t)]) for t in th]

    ii0, oo0 = ring(y0, r_in0), ring(y0, r_out0)
    ii1, oo1 = ring(y1, r_in1), ring(y1, r_out1)
    for i in range(n_theta):
        j = (i + 1) % n_theta
        add_quad(tris, oo0[i], oo0[j], oo1[j], oo1[i])
        add_quad(tris, ii0[j], ii0[i], ii1[i], ii1[j])
        add_quad(tris, ii0[i], ii0[j], oo0[j], oo0[i])
        add_quad(tris, ii1[j], ii1[i], oo1[i], oo1[j])


def airfoil(ch, t_c=0.08, n=18):
    xs = np.linspace(0, 1, n)
    yt = (
        5
        * t_c
        * (
            0.2969 * np.sqrt(np.maximum(xs, 0))
            - 0.1260 * xs
            - 0.3516 * xs**2
            + 0.2843 * xs**3
            - 0.1036 * xs**4
        )
    )
    upper = [(float(xs[i] * ch), float(yt[i] * ch)) for i in range(n)]
    lower = [(float(xs[i] * ch), float(-yt[i] * ch)) for i in range(n - 1, 0, -1)]
    return upper + lower


def blade(
    tris,
    y_le,
    r_hub,
    r_tip,
    ch_h,
    ch_t,
    pitch_h,
    pitch_t,
    n_span=12,
    n_sec=18,
    t_c=0.08,
    invert_chord_axial=True,
):
    """
    Blade loft. Pitch angle is geometric φ about the radial axis:
      dy = ± s_ch * cos(φ)   (axial)
      dz =   s_ch * sin(φ)   (tangential)
    invert_chord_axial=True → jet sense −y for freestream (0,−Va,0).
    """
    ax_sign = -1.0 if invert_chord_axial else 1.0
    profs = []
    for s in np.linspace(0, 1, n_span):
        r = r_hub + s * (r_tip - r_hub)
        ch = ch_h + s * (ch_t - ch_h)
        pitch = pitch_h + s * (pitch_t - pitch_h)
        sec = airfoil(ch, t_c, n_sec)
        ca, sa = math.cos(pitch), math.sin(pitch)
        pts = []
        for xc, tc in sec:
            s_ch = xc - 0.3 * ch
            dy = ax_sign * s_ch * ca
            dz = s_ch * sa
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
    hub_r = 0.030
    tip_clear = 0.004
    r_tip = R - tip_clear
    Zr, Zs = 5, 7  # fewer blades → lower solidity / torque

    # Light cruise loading: P/D modest, J high → KT ~ 0.05–0.1 → T ~ 150–350 N
    J_des = 0.90
    P_over_D = 0.85  # slightly under geometric match at mid-span for mild load

    def pitch_at(r):
        return math.atan(P_over_D * D / (2 * math.pi * max(r, 1e-6)))

    rotor: List[Tri] = []
    cylinder_solid(rotor, -0.018, 0.030, hub_r, 48)
    for i in range(Zr):
        one: List[Tri] = []
        blade(
            one,
            y_le=-0.002,
            r_hub=hub_r * 1.03,
            r_tip=r_tip,
            ch_h=0.028,  # short chord
            ch_t=0.018,
            pitch_h=pitch_at(hub_r * 1.2),
            pitch_t=pitch_at(0.75 * R),
            n_span=11,
            n_sec=16,
            t_c=0.08,
            invert_chord_axial=True,
        )
        rotor.extend(rot_tris(one, 2 * math.pi * i / Zr))

    duct: List[Tri] = []
    y_in, y_out = -0.055, 0.11
    annular_duct(
        duct,
        y_in,
        y_out,
        r_in0=R + 0.002,
        r_out0=R + 0.012,
        r_in1=0.93 * R,
        r_out1=0.93 * R + 0.011,
        n_theta=80,
    )
    for i in range(Zs):
        one = []
        blade(
            one,
            y_le=0.038,
            r_hub=hub_r + 0.012,
            r_tip=0.90 * R,
            ch_h=0.024,
            ch_t=0.018,
            pitch_h=-(pitch_at(hub_r * 1.3) * 0.70),
            pitch_t=-(pitch_at(0.7 * R) * 0.50),
            n_span=8,
            n_sec=14,
            t_c=0.08,
            invert_chord_axial=False,
        )
        duct.extend(rot_tris(one, 2 * math.pi * i / Zs + math.pi / Zs))

    out_dir = Path(out_dir)
    write_binary_stl(out_dir / "rotor.stl", rotor, "rotor")
    write_binary_stl(out_dir / "duct_stator.stl", duct, "duct_stator")

    rpm = 3000.0  # ≥ 3000
    n = rpm / 60.0
    Va = J_des * n * D
    # Expected T ≈ KT * ρ * n² * D⁴ with KT≈0.06
    T_est = 0.06 * 1000.0 * (n**2) * (D**4)

    meta = {
        "version": 3,
        "D": D,
        "hub_ratio": 2 * hub_r / D,
        "Zr": Zr,
        "Zs": Zs,
        "pitch_ratio": P_over_D,
        "design_J": J_des,
        "tip_clearance_m": tip_clear,
        "duct_length_m": y_out - y_in,
        "rpm": rpm,
        "Va": Va,
        "J": Va / (n * D),
        "rho": 1000.0,
        "target_thrust_N": 100.0,
        "estimated_thrust_N": T_est,
        "target_eta_p": 0.6,
        "nprocs": 6,
        "axis": [0, 1, 0],
        "u_inf": [0, -Va, 0],
        "notes": (
            "v3 moderate load: P/D=0.85, J=0.90, 5×7, 3000 rpm, Va≈9 m/s, "
            "ρ=1000; aim T~100–300 N (KT~0.06), meridional through-flow viz."
        ),
    }
    (out_dir / "design_params.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    return meta


if __name__ == "__main__":
    generate(Path(__file__).resolve().parent / "geometry_v3")

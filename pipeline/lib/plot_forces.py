#!/usr/bin/env python3
"""
Plot propulsor efficiency, thrust, and torque vs time from OpenFOAM forces.dat.

Usage:
  plot_forces.py --forces path/to/forces.dat --out-dir path/to/plots \\
      [--rpm 1500] [--axis 0 1 0] [--u-inf 0 -5 0] [--meta pipeline_meta.json]
      [--rho 1000] [--diameter 0.2]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Optional, Sequence, Tuple

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, AutoMinorLocator


PAT = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"\(\(\s*([^\)]+)\)\s*\(\s*([^\)]+)\)\)\s+"
    r"\(\(\s*([^\)]+)\)\s*\(\s*([^\)]+)\)\)"
)


def vec3(s: str) -> np.ndarray:
    return np.array([float(x) for x in s.split()], dtype=float)


def froude_efficiency(T: np.ndarray, va: float, rho: float, diameter: float) -> np.ndarray:
    """Ideal propulsive (Froude) efficiency from thrust loading.

    η_p = 2 / (1 + sqrt(1 + C_T)),  C_T = T / (½ ρ A V_a²),  A = π D²/4.
    This is the classical jet-propulsor figure of merit for a given thrust.
    """
    A = 0.25 * np.pi * max(diameter, 1e-9) ** 2
    dyn = 0.5 * rho * va * va * A
    ct = np.where((dyn > 1e-15) & (T > 0), T / dyn, np.nan)
    return 2.0 / (1.0 + np.sqrt(1.0 + ct))


def load_forces(
    forces_path: Path,
    axis: np.ndarray,
    u_inf: np.ndarray,
    rpm: float,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    axis = np.asarray(axis, dtype=float)
    axis = axis / (np.linalg.norm(axis) + 1e-15)
    u_inf = np.asarray(u_inf, dtype=float)
    va = float(np.linalg.norm(u_inf))
    adv = -u_inf / (va + 1e-15)  # advance direction (into freestream)
    omega = rpm * 2.0 * np.pi / 60.0

    t_list, T_list, Q_list, eta_list = [], [], [], []
    with forces_path.open() as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = PAT.match(line)
            if not m:
                continue
            t = float(m.group(1))
            F = vec3(m.group(2)) + vec3(m.group(3))
            M = vec3(m.group(4)) + vec3(m.group(5))
            thrust = float(np.dot(F, adv))
            torque = float(np.dot(M, axis))  # signed about rotation axis
            power = abs(torque) * omega
            useful = thrust * va
            eta = useful / power if (power > 1e-12 and thrust > 0) else np.nan
            t_list.append(t)
            T_list.append(thrust)
            Q_list.append(torque)
            eta_list.append(eta)

    t = np.asarray(t_list)
    T = np.asarray(T_list)
    Q = np.asarray(Q_list)
    eta = np.asarray(eta_list)
    rev = t * (rpm / 60.0)
    return t, rev, T, Q, eta


def _ss_mask(t: np.ndarray) -> np.ndarray:
    """Post-startup window for mean stats (last ~75% of the run)."""
    if len(t) == 0:
        return np.array([], dtype=bool)
    t_end = float(t[-1])
    if t_end <= 0:
        return np.ones_like(t, dtype=bool)
    t0 = min(0.25 * t_end, max(0.0, t_end - 1e-12))
    return t >= t0


def _ylim_from_ss(y: np.ndarray, mask: np.ndarray, pad_frac: float = 0.15, floor0: bool = False):
    if not mask.any():
        return None
    lo, hi = np.percentile(y[mask], [1, 99])
    pad = pad_frac * (hi - lo + 1e-12)
    ymin, ymax = lo - pad, hi + pad
    if floor0:
        ymin = max(0.0, ymin)
    return ymin, ymax


def plot_performance(
    t: np.ndarray,
    rev: np.ndarray,
    T: np.ndarray,
    Q: np.ndarray,
    eta: np.ndarray,
    rpm: float,
    va: float,
    out_dir: Path,
    title_suffix: str = "",
    eta_p: Optional[np.ndarray] = None,
    primary: str = "shaft",
) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    mask = _ss_mask(t)

    def _stats(arr: np.ndarray, lo: float = 0.0, hi: float = 2.0):
        if not mask.any():
            return float("nan"), float("nan"), float("nan")
        v = arr[mask]
        ok = np.isfinite(v) & (v > lo) & (v < hi)
        if not ok.any():
            return float("nan"), float("nan"), float("nan")
        return float(np.mean(v[ok])), float(np.median(v[ok])), float(v[ok][-1])

    # Primary efficiency for headline stats / mean lines
    if primary == "froude" and eta_p is not None:
        eta_plot = eta_p
        eta_label = r"Froude propulsive $\eta_p=2/(1+\sqrt{1+C_T})$"
        eta_yl = r"Efficiency $\eta_p$ [-]"
    else:
        eta_plot = eta
        eta_label = r"Shaft $\eta_0=T V_a/(Q\omega)$"
        eta_yl = r"Efficiency $\eta_0$ [-]"

    eta_mean, eta_med, eta_last = _stats(eta_plot)
    eta0_mean, _, eta0_last = _stats(eta)
    etap_mean = etap_med = etap_last = float("nan")
    if eta_p is not None:
        etap_mean, etap_med, etap_last = _stats(eta_p)

    T_mean = float(np.mean(T[mask])) if mask.any() else float("nan")
    Q_mean = float(np.mean(Q[mask])) if mask.any() else float("nan")
    Q_abs_mean = float(np.mean(np.abs(Q[mask]))) if mask.any() else float("nan")
    omega = rpm * 2.0 * np.pi / 60.0

    # CSV
    csv_path = out_dir / "propulsor_efficiency.csv"
    with csv_path.open("w") as f:
        f.write("time_s,revolutions,thrust,torque,torque_abs,eta0_shaft,eta_p_froude\n")
        for i in range(len(t)):
            e0 = f"{eta[i]:.8g}" if np.isfinite(eta[i]) else ""
            ep = ""
            if eta_p is not None and np.isfinite(eta_p[i]):
                ep = f"{eta_p[i]:.8g}"
            f.write(
                f"{t[i]:.8g},{rev[i]:.8g},{T[i]:.8g},{Q[i]:.8g},{abs(Q[i]):.8g},{e0},{ep}\n"
            )

    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.titlesize": 11,
            "axes.labelsize": 10,
            "legend.fontsize": 9,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )

    fig, axes = plt.subplots(
        3,
        1,
        figsize=(11, 9.5),
        sharex=True,
        gridspec_kw={"height_ratios": [1.35, 1.1, 1.1], "hspace": 0.14},
    )

    def add_rev_axis(ax):
        if len(t) < 2 or t[-1] <= t[0]:
            return None
        ax_top = ax.twiny()
        ax_top.set_xlim(rev[0], rev[-1])
        ax_top.set_xlabel("Propeller revolutions")
        ax_top.xaxis.set_major_locator(MaxNLocator(nbins=8))
        return ax_top

    # --- Efficiency vs time ---
    ax = axes[0]
    if eta_p is not None:
        ax.plot(t, eta_p, color="#0b5cab", lw=2.0, label=r"Froude propulsive $\eta_p$")
        ax.plot(t, eta, color="#7f8c8d", lw=1.2, alpha=0.85, label=r"Shaft $\eta_0=T V_a/(Q\omega)$")
        if np.isfinite(etap_mean):
            ax.axhline(
                etap_mean,
                color="#c0392b",
                ls="--",
                lw=1.3,
                label=fr"Mean $\eta_p$ (post-startup): {etap_mean:.3f}",
            )
        ax.axhline(0.6, color="#1e8449", ls=":", lw=1.4, label=r"Target $\eta_p=0.6$")
        ax.set_ylabel(r"Efficiency [-]")
        last_txt = rf"Last $\eta_p={etap_last:.3f}$, $\eta_0={eta0_last:.3f}$"
    else:
        ax.plot(t, eta, color="#0b5cab", lw=1.6, label=eta_label)
        if np.isfinite(eta_mean):
            ax.axhline(eta_mean, color="#c0392b", ls="--", lw=1.25, label=fr"Mean: {eta_mean:.3f}")
        ax.set_ylabel(eta_yl)
        last_txt = rf"Last $\eta_0={eta_last:.3f}$"
    ax.set_ylim(0.0, 1.05)
    ax.legend(loc="lower right", framealpha=0.95, fontsize=8)
    ax.grid(True, alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())
    title = fr"Propulsor performance vs time — $n={rpm:.0f}$ rpm, $|V_a|={va:.2f}$ m/s"
    if title_suffix:
        title += f"\n{title_suffix}"
    ax.set_title(title)
    ax.text(
        0.015,
        0.96,
        rf"$\omega = 2\pi n = {omega:.2f}$ rad/s" + "\n" + last_txt,
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=9,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white", edgecolor="#cccccc", alpha=0.95),
    )
    add_rev_axis(ax)

    # --- Thrust vs time ---
    ax = axes[1]
    ax.plot(t, T, color="#e67e22", lw=1.5, label=r"Thrust $T$ (advance direction)")
    if np.isfinite(T_mean):
        ax.axhline(T_mean, color="#922b21", ls="--", lw=1.2, label=fr"Mean (post-startup): {T_mean:.4g}")
    ax.axhline(100.0, color="#1e8449", ls=":", lw=1.3, label=r"Target $T=100$ N")
    yl = _ylim_from_ss(T, mask)
    if yl:
        # ensure target line visible if T is large
        ax.set_ylim(min(yl[0], 0), max(yl[1], 120))
    ax.set_ylabel(r"Thrust $T$  [N]  ($\rho_\mathrm{inf}$ applied)")
    ax.legend(loc="best", framealpha=0.95, fontsize=8)
    ax.grid(True, alpha=0.35)
    ax.yaxis.set_minor_locator(AutoMinorLocator())

    # --- Torque vs time ---
    ax = axes[2]
    ax.plot(t, Q, color="#6c3483", lw=1.5, label=r"Torque $Q$ (about rotation axis)")
    if np.isfinite(Q_mean):
        ax.axhline(
            Q_mean,
            color="#4a235a",
            ls="--",
            lw=1.2,
            label=fr"Mean $Q$ (post-startup): {Q_mean:.4g}  ($|Q|={Q_abs_mean:.4g}$)",
        )
    yl = _ylim_from_ss(Q, mask)
    if yl:
        ax.set_ylim(*yl)
    ax.set_ylabel(r"Torque $Q$  [N·m]")
    ax.set_xlabel("Time $t$ [s]")
    ax.legend(loc="best", framealpha=0.95, fontsize=8)
    ax.grid(True, alpha=0.35)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=10))
    ax.yaxis.set_minor_locator(AutoMinorLocator())

    fig.align_ylabels(axes)
    png = out_dir / "propulsor_efficiency.png"
    pdf = out_dir / "propulsor_efficiency.pdf"
    fig.savefig(png, dpi=170, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)

    # Thrust+torque companion
    fig2, axes2 = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True, gridspec_kw={"hspace": 0.12})
    ax = axes2[0]
    ax.plot(t, T, color="#e67e22", lw=1.6, label="Thrust $T$")
    if np.isfinite(T_mean):
        ax.axhline(T_mean, color="#922b21", ls="--", lw=1.2, label=f"Mean: {T_mean:.4g}")
    ax.axhline(100.0, color="#1e8449", ls=":", lw=1.2, label="Target 100 N")
    yl = _ylim_from_ss(T, mask)
    if yl:
        ax.set_ylim(min(yl[0], 0), max(yl[1], 120))
    ax.set_ylabel(r"Thrust $T$ [N]")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.35)
    ax.set_title(fr"Thrust and torque vs time — $n={rpm:.0f}$ rpm")
    add_rev_axis(ax)

    ax = axes2[1]
    ax.plot(t, Q, color="#6c3483", lw=1.6, label="Torque $Q$ (rotation axis)")
    if np.isfinite(Q_mean):
        ax.axhline(
            Q_mean,
            color="#4a235a",
            ls="--",
            lw=1.2,
            label=f"Mean $Q$: {Q_mean:.4g}  ($|Q|={Q_abs_mean:.4g}$)",
        )
    yl = _ylim_from_ss(Q, mask)
    if yl:
        ax.set_ylim(*yl)
    ax.set_ylabel(r"Torque $Q$ [N·m]")
    ax.set_xlabel("Time $t$ [s]")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.35)

    fig2.savefig(out_dir / "propulsor_thrust_torque.png", dpi=170, bbox_inches="tight")
    fig2.savefig(out_dir / "propulsor_thrust_torque.pdf", bbox_inches="tight")
    plt.close(fig2)

    # Headline eta: prefer Froude when requested / available
    headline = etap_mean if (primary == "froude" and np.isfinite(etap_mean)) else eta_mean

    stats = {
        "eta_mean": headline,
        "eta_med": eta_med,
        "eta_last": eta_last,
        "eta0_mean": eta0_mean,
        "etap_mean": etap_mean,
        "T_mean": T_mean,
        "Q_mean": Q_mean,
        "Q_abs_mean": Q_abs_mean,
        "png": str(png),
        "pdf": str(pdf),
        "csv": str(csv_path),
    }
    return stats


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--forces", type=Path, required=True, help="Path to forces.dat")
    p.add_argument("--out-dir", type=Path, required=True, help="Output directory for plots/CSV")
    p.add_argument("--rpm", type=float, default=1500.0)
    p.add_argument("--axis", type=float, nargs=3, default=[0.0, 1.0, 0.0])
    p.add_argument("--u-inf", type=float, nargs=3, default=[0.0, -5.0, 0.0])
    p.add_argument("--meta", type=Path, default=None, help="Optional pipeline_meta.json")
    p.add_argument("--title-suffix", type=str, default="")
    p.add_argument("--rho", type=float, default=1.0, help="Density used for Froude CT [kg/m^3]")
    p.add_argument("--diameter", type=float, default=0.0, help="Rotor diameter [m] for Froude CT")
    p.add_argument(
        "--primary-eta",
        choices=("shaft", "froude"),
        default="shaft",
        help="Which efficiency is the headline mean (shaft η0 or Froude ηp)",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_args(argv)
    rpm = args.rpm
    axis = np.array(args.axis, dtype=float)
    u_inf = np.array(args.u_inf, dtype=float)
    rho = float(args.rho)
    diameter = float(args.diameter)

    if args.meta and args.meta.is_file():
        meta = json.loads(args.meta.read_text())
        rpm = float(meta.get("rpm", rpm))
        if "axis" in meta:
            axis = np.array(meta["axis"], dtype=float)
        if "u_inf" in meta:
            u_inf = np.array(meta["u_inf"], dtype=float)
        if "D" in meta.get("domain", {}):
            diameter = float(meta["domain"]["D"])
        elif "D" in meta:
            diameter = float(meta["D"])
        # design_params style
        if diameter <= 0 and "D" in meta:
            diameter = float(meta["D"])

    if not args.forces.is_file():
        raise SystemExit(f"forces.dat not found: {args.forces}")

    t, rev, T, Q, eta0 = load_forces(args.forces, axis, u_inf, rpm)
    if len(t) == 0:
        raise SystemExit(f"No force samples parsed from {args.forces}")

    va = float(np.linalg.norm(u_inf))
    eta_p = None
    if diameter > 0 and rho > 0:
        eta_p = froude_efficiency(T, va, rho, diameter)

    stats = plot_performance(
        t,
        rev,
        T,
        Q,
        eta0,
        rpm,
        va,
        args.out_dir,
        args.title_suffix,
        eta_p=eta_p,
        primary=args.primary_eta,
    )
    print("Wrote", stats["png"])
    print("Wrote", stats["pdf"])
    print("Wrote", Path(stats["csv"]).parent / "propulsor_thrust_torque.png")
    # Non-dimensional coeffs (sanity check on thrust magnitude)
    n = rpm / 60.0
    if diameter > 0 and rho > 0 and n > 0:
        KT = stats["T_mean"] / (rho * n**2 * diameter**4 + 1e-30)
        KQ = abs(stats["Q_mean"]) / (rho * n**2 * diameter**5 + 1e-30)
        J = va / (n * diameter + 1e-30)
    else:
        KT = KQ = J = float("nan")
    print(
        f"eta_mean={stats['eta_mean']:.4f}  eta0_mean={stats.get('eta0_mean', float('nan')):.4f}  "
        f"etap_mean={stats.get('etap_mean', float('nan')):.4f}  "
        f"T_mean={stats['T_mean']:.6g}  Q_mean={stats['Q_mean']:.6g}  |Q|_mean={stats['Q_abs_mean']:.6g}"
    )
    print(
        f"coeffs: J={J:.4f}  KT={KT:.4f}  KQ={KQ:.5f}  "
        f"(cruise KT typically ~0.05–0.25; KT≫0.4 suggests overload / check ρ_inf)"
    )


if __name__ == "__main__":
    main()

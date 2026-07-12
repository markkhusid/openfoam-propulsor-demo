#!/usr/bin/env python3
"""Plot open-water propulsor efficiency from OpenFOAM forces.dat."""
import re
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

CASE = Path(__file__).resolve().parent
forces_path = CASE / "results" / "forces" / "forces.dat"
if not forces_path.is_file():
    forces_path = CASE / "postProcessing" / "forces" / "0" / "forces.dat"
out_dir = CASE / "results" / "plots"
out_dir.mkdir(parents=True, exist_ok=True)

rpm = 1500.0
omega = rpm * 2.0 * np.pi / 60.0
Va = 5.0
n_rps = rpm / 60.0

pat = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"\(\(\s*([^\)]+)\)\s*\(\s*([^\)]+)\)\)\s+"
    r"\(\(\s*([^\)]+)\)\s*\(\s*([^\)]+)\)\)"
)

def vec3(s):
    return np.array([float(x) for x in s.split()], dtype=float)

times, T_list, Q_list, eta_list = [], [], [], []
with forces_path.open() as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = pat.match(line)
        if not m:
            continue
        t = float(m.group(1))
        F = vec3(m.group(2)) + vec3(m.group(3))
        M = vec3(m.group(4)) + vec3(m.group(5))
        thrust, torque = F[1], M[1]
        power = abs(torque) * omega
        eta = (thrust * Va) / power if (power > 1e-12 and thrust > 0) else np.nan
        times.append(t); T_list.append(thrust); Q_list.append(torque); eta_list.append(eta)

t = np.asarray(times); T = np.asarray(T_list); Q = np.asarray(Q_list); eta = np.asarray(eta_list)
rev = t * n_rps
mask_ss = t >= 0.02
valid = np.isfinite(eta[mask_ss]) & (eta[mask_ss] > 0) & (eta[mask_ss] < 2.0)
eta_mean = float(np.mean(eta[mask_ss][valid]))
eta_med = float(np.median(eta[mask_ss][valid]))
eta_last = float(eta[np.isfinite(eta)][-1])
T_mean = float(np.mean(T[mask_ss]))
Q_mean = float(np.mean(np.abs(Q[mask_ss])))

csv_path = out_dir / "propulsor_efficiency.csv"
with csv_path.open("w") as f:
    f.write("time_s,revolutions,thrust_per_rho,torque_per_rho,efficiency\n")
    for i in range(len(t)):
        e = f"{eta[i]:.8g}" if np.isfinite(eta[i]) else ""
        f.write(f"{t[i]:.8g},{rev[i]:.8g},{T[i]:.8g},{Q[i]:.8g},{e}\n")

fig, axes = plt.subplots(3, 1, figsize=(10.5, 9.2), sharex=True,
                         gridspec_kw={"height_ratios": [1.4, 1.0, 1.0], "hspace": 0.12})
ax = axes[0]
ax.plot(rev, eta, color="#0b5cab", lw=1.6, label=r"$\eta_0=TV_a/(Q\omega)$")
ax.axhline(eta_mean, color="#c0392b", ls="--", lw=1.3, label=fr"Mean: {eta_mean:.3f}")
ax.axhline(eta_med, color="#1e8449", ls=":", lw=1.4, label=fr"Median: {eta_med:.3f}")
ax.set_ylabel(r"$\eta_0$ [-]"); ax.set_ylim(0, 1); ax.legend(loc="lower right"); ax.grid(True, alpha=0.35)
ax.set_title(fr"Propulsor efficiency — $n={rpm:.0f}$ rpm, $V_a={Va:.1f}$ m/s")
ax = axes[1]
ax.plot(rev, T, color="#e67e22", lw=1.4); ax.axhline(T_mean, color="#922b21", ls="--", lw=1.1)
ss = T[mask_ss]; lo, hi = np.percentile(ss, [1, 99]); pad = 0.15 * (hi - lo + 1e-9)
ax.set_ylim(max(0, lo - pad), hi + pad); ax.set_ylabel(r"$T/\rho$"); ax.grid(True, alpha=0.35)
ax = axes[2]
ax.plot(rev, np.abs(Q), color="#6c3483", lw=1.4); ax.axhline(Q_mean, color="#4a235a", ls="--", lw=1.1)
ss = np.abs(Q[mask_ss]); lo, hi = np.percentile(ss, [1, 99]); pad = 0.15 * (hi - lo + 1e-9)
ax.set_ylim(max(0, lo - pad), hi + pad); ax.set_ylabel(r"$|Q|/\rho$"); ax.set_xlabel("Revolutions"); ax.grid(True, alpha=0.35)
fig.savefig(out_dir / "propulsor_efficiency.png", dpi=170, bbox_inches="tight")
fig.savefig(out_dir / "propulsor_efficiency.pdf", bbox_inches="tight")
print("Wrote plots to", out_dir)
print(f"eta_mean={eta_mean:.4f} eta_last={eta_last:.4f}")

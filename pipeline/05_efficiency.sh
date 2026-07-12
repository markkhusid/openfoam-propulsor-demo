#!/usr/bin/env bash
# Plot open-water style propulsor efficiency from forces.dat
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=/dev/null
source "$DIR/lib/common.sh"

load_config "${1:-}"
[[ -d "${CASE_DIR:-}" ]] || die "CASE_DIR missing"

forces=$(find "$CASE_DIR/postProcessing/forces" -name forces.dat 2>/dev/null | head -1 || true)
[[ -n "$forces" && -f "$forces" ]] || die "No forces.dat under $CASE_DIR/postProcessing/forces"

meta="$CASE_DIR/pipeline_meta.json"
out="$CASE_DIR/postProcessing/plots"
mkdir -p "$out"

python3 - <<PY
import json, re, os
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

forces_path = Path(r"""$forces""")
out_dir = Path(r"""$out""")
meta_path = Path(r"""$meta""")

rpm = float(os.environ.get("RPM", "1500"))
axis = np.array([float(x) for x in os.environ.get("ROT_AXIS", "0 1 0").split()], dtype=float)
u_inf = np.array([float(x) for x in os.environ.get("U_INF", "0 -5 0").split()], dtype=float)
if meta_path.is_file():
    m = json.load(meta_path.open())
    rpm = float(m.get("rpm", rpm))
    axis = np.array(m.get("axis", axis), dtype=float)
    u_inf = np.array(m.get("u_inf", u_inf), dtype=float)

axis = axis / (np.linalg.norm(axis) + 1e-15)
omega = rpm * 2 * np.pi / 60.0
Va = float(np.linalg.norm(u_inf))
n_rps = rpm / 60.0

# Advance direction: opposite to freestream (vehicle heading into flow)
adv = -u_inf / (Va + 1e-15)

pat = re.compile(
    r"^\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s+"
    r"\(\(\s*([^\)]+)\)\s*\(\s*([^\)]+)\)\)\s+"
    r"\(\(\s*([^\)]+)\)\s*\(\s*([^\)]+)\)\)"
)

def vec3(s):
    return np.array([float(x) for x in s.split()])

t_list, T_list, Q_list, eta_list = [], [], [], []
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
        thrust = float(np.dot(F, adv))  # force in advance direction
        torque = float(np.dot(M, axis))
        power = abs(torque) * omega
        useful = thrust * Va
        eta = useful / power if (power > 1e-12 and thrust > 0) else np.nan
        t_list.append(t); T_list.append(thrust); Q_list.append(torque); eta_list.append(eta)

t = np.asarray(t_list); T = np.asarray(T_list); Q = np.asarray(Q_list); eta = np.asarray(eta_list)
rev = t * n_rps
mask = t >= max(0.02, 0.25 * (t[-1] if len(t) else 1))
valid = np.isfinite(eta[mask]) & (eta[mask] > 0) & (eta[mask] < 2)
eta_mean = float(np.mean(eta[mask][valid])) if valid.any() else float("nan")
eta_med = float(np.median(eta[mask][valid])) if valid.any() else float("nan")
eta_last = float(eta[np.isfinite(eta)][-1]) if np.isfinite(eta).any() else float("nan")
T_mean = float(np.mean(T[mask])) if mask.any() else float("nan")
Q_mean = float(np.mean(np.abs(Q[mask]))) if mask.any() else float("nan")

csv = out_dir / "propulsor_efficiency.csv"
with csv.open("w") as f:
    f.write("time_s,revolutions,thrust,torque,efficiency\n")
    for i in range(len(t)):
        e = f"{eta[i]:.8g}" if np.isfinite(eta[i]) else ""
        f.write(f"{t[i]:.8g},{rev[i]:.8g},{T[i]:.8g},{Q[i]:.8g},{e}\n")

fig, axes = plt.subplots(3, 1, figsize=(10.5, 9.2), sharex=True,
                         gridspec_kw={"height_ratios": [1.4, 1.0, 1.0], "hspace": 0.12})
ax = axes[0]
ax.plot(rev, eta, color="#0b5cab", lw=1.6, label=r"$\eta_0 = T V_a / (Q \omega)$")
if np.isfinite(eta_mean):
    ax.axhline(eta_mean, color="#c0392b", ls="--", lw=1.3, label=f"Mean: {eta_mean:.3f}")
if np.isfinite(eta_med):
    ax.axhline(eta_med, color="#1e8449", ls=":", lw=1.4, label=f"Median: {eta_med:.3f}")
ax.set_ylabel(r"$\eta_0$ [-]"); ax.set_ylim(0, 1); ax.legend(loc="lower right"); ax.grid(True, alpha=0.35)
ax.set_title(f"Propulsor efficiency — n={rpm:.0f} rpm, |Va|={Va:.2f} m/s")
ax.text(0.02, 0.96, f"Last η₀={eta_last:.3f}\nω={omega:.2f} rad/s", transform=ax.transAxes,
        va="top", fontsize=9, bbox=dict(boxstyle="round", facecolor="white", alpha=0.9))

ax = axes[1]
ax.plot(rev, T, color="#e67e22", lw=1.4)
if np.isfinite(T_mean):
    ax.axhline(T_mean, color="#922b21", ls="--", lw=1.1)
if mask.any():
    lo, hi = np.percentile(T[mask], [1, 99]); pad = 0.15 * (hi - lo + 1e-9)
    ax.set_ylim(lo - pad, hi + pad)
ax.set_ylabel("Thrust (advance dir.)"); ax.grid(True, alpha=0.35)

ax = axes[2]
ax.plot(rev, np.abs(Q), color="#6c3483", lw=1.4)
if np.isfinite(Q_mean):
    ax.axhline(Q_mean, color="#4a235a", ls="--", lw=1.1)
if mask.any():
    lo, hi = np.percentile(np.abs(Q[mask]), [1, 99]); pad = 0.15 * (hi - lo + 1e-9)
    ax.set_ylim(max(0, lo - pad), hi + pad)
ax.set_ylabel("|Torque|"); ax.set_xlabel("Revolutions"); ax.grid(True, alpha=0.35)
ax.xaxis.set_major_locator(MaxNLocator(nbins=10))

fig.savefig(out_dir / "propulsor_efficiency.png", dpi=170, bbox_inches="tight")
fig.savefig(out_dir / "propulsor_efficiency.pdf", bbox_inches="tight")
print("Wrote", out_dir / "propulsor_efficiency.png")
print(f"eta_mean={eta_mean:.4f} eta_last={eta_last:.4f}")
PY

info "Efficiency plots in $out"
ls -lh "$out"

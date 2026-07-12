#!/usr/bin/env python3
"""Plot efficiency, thrust, and torque vs time for the demo case."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pipeline" / "lib"))

from plot_forces import load_forces, plot_performance  # noqa: E402
import numpy as np

forces_path = ROOT / "results" / "forces" / "forces.dat"
if not forces_path.is_file():
    forces_path = ROOT / "postProcessing" / "forces" / "0" / "forces.dat"
out_dir = ROOT / "results" / "plots"
out_dir.mkdir(parents=True, exist_ok=True)

rpm = 1500.0
axis = np.array([0.0, 1.0, 0.0])
u_inf = np.array([0.0, -5.0, 0.0])

t, rev, T, Q, eta = load_forces(forces_path, axis, u_inf, rpm)
va = float(np.linalg.norm(u_inf))
stats = plot_performance(
    t, rev, T, Q, eta, rpm, va, out_dir, title_suffix="OpenFOAM tutorial propeller (demo)"
)

# Convenience copies at repo root
for name in (
    "propulsor_efficiency.png",
    "propulsor_efficiency.pdf",
    "propulsor_thrust_torque.png",
    "propulsor_thrust_torque.pdf",
):
    src = out_dir / name
    if src.is_file():
        (ROOT / name).write_bytes(src.read_bytes())

print("Wrote plots to", out_dir)
print(
    f"eta_mean={stats['eta_mean']:.4f}  T_mean={stats['T_mean']:.6g}  "
    f"Q_mean={stats['Q_mean']:.6g}"
)

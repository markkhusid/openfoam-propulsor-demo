# OpenFOAM Propulsor Demo

Coarse-mesh **transient marine propeller** case (OpenFOAM 11) run as a VM-sized demonstration of:

1. Rotating-propulsor CFD with non-conformal sliding interfaces  
2. Surface sampling for a short engineering **flow movie**  
3. Force/moment post-processing and **open-water efficiency** \(\eta_0 = T V_a / (Q \omega)\)

> Demo quality (~86k cells, ~2 revolutions). Not a design-grade open-water curve.

## Deliverables

| File | Description |
|------|-------------|
| [`propeller_flow_10s.mp4`](propeller_flow_10s.mp4) | 10 s, 1280×720 flow movie (mid-plane \(\|U\|\) + blades) |
| [`propulsor_efficiency.png`](propulsor_efficiency.png) | Efficiency / thrust / torque vs revolutions |
| [`propulsor_efficiency.pdf`](propulsor_efficiency.pdf) | Vector version of the plot |
| [`results/forces/forces.dat`](results/forces/forces.dat) | OpenFOAM forces history |
| [`results/plots/propulsor_efficiency.csv`](results/plots/propulsor_efficiency.csv) | Tabulated efficiency time series |

**Summary (this demo run)**

- \(n = 1500\) rpm, \(V_a = 5\) m/s, \(\rho = 1\) (kinematic forces)  
- Mean \(\eta_0 \approx 0.56\) after startup (\(t \ge 0.02\) s)  
- Wall time ~1 hour on 4 cores / ~16 GB VM  

## Case layout

```
0/ system/ constant/   # OpenFOAM case (OF11 incompressibleFluid + solidBody rotation)
Allmesh Allrun         # Mesh (snappy + NCC) and parallel solve
run_and_movie.sh       # Disk-capped solve + ParaView/ffmpeg movie pipeline
make_movie.py          # pvpython frame generation
encode_movie.sh        # PNG sequence → MP4
plot_efficiency.py     # Recompute efficiency plots from forces.dat
```

## How to re-run (OpenFOAM 11 Docker)

Requires Docker image `openfoam/openfoam11-paraview510` and a host helper that mounts the case, or an equivalent OF11 install.

```bash
# Mesh (once)
./Allmesh

# Solve (4 ranks by default in system/decomposeParDict)
decomposePar -fields -copyZero
mpirun -np 4 foamRun -parallel
# optional: reconstructPar

# Efficiency plot (host Python with numpy/matplotlib)
python3 plot_efficiency.py
```

Or use the bundled pipeline script (see `run_and_movie.sh`) if you have the `openfoam` Docker wrapper from the original VM setup.

## Physics notes

- Solver: `foamRun` / `incompressibleFluid`  
- Motion: solid-body rotation of `innerCylinder` zone @ 1500 rpm about **y**  
- Sliding interface: non-conformal couples (`nonCouple1` / `nonCouple2`)  
- Inlet: \((0,-5,0)\) m/s; advance direction taken as \(+y\) for thrust \(T=F_y\)  
- Torque: \(|Q|=|M_y|\); \(\omega = 2\pi n\)

## License / attribution

OpenFOAM is GPL. Tutorial geometry originates from the OpenFOAM Foundation tutorial `incompressibleFluid/propeller`.  
Case tuning, automation, movie, and efficiency post-processing by Mark Khusid.

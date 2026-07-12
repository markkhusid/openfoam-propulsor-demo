# Full pipeline: arbitrary watertight STL → CFD → movie → efficiency

This guide describes how to take a **watertight CAD solid** of a propulsor or **pumpjet rotor** (and optional duct/stator STLs), run a transient OpenFOAM simulation with a rotating mesh zone, and produce:

1. An engineering **flow movie** (10 s demo, or 30–60 s on larger machines)  
2. A **propulsor efficiency** plot \(\eta_0 = T V_a / (Q \omega)\)

The automation lives under [`pipeline/`](../pipeline/).

---

## 1. What you need

### Geometry (CAD)

| Item | Requirement |
|------|-------------|
| **Rotor STL** | Single **watertight** (closed manifold) solid of the rotating assembly |
| **Units** | Prefer **metres**. If CAD is in mm, set `STL_SCALE=0.001` |
| **Optional stator/duct** | One or more stationary watertight STLs (`STATOR_STLS`) |
| **Orientation** | Document the shaft axis; set `ROT_AXIS` and `U_INF` consistently |

**Pumpjet notes**

- Typical setup: **rotor** STL (rotating) + **duct/stator** STL(s) (fixed).  
- Both must be closed solids. Gaps between rotor tip and duct are physical — do **not** boolean them into one body if you need relative rotation.  
- Align the duct and rotor in the same coordinate system before export.

**How to check “watertight”**

- CAD: “make solid”, stitch edges, no free edges.  
- Pipeline runs a lightweight edge-manifold check and prints a warning if open.  
- OpenFOAM `snappyHexMesh` will leak or fail on open surfaces.

### Software

| Mode | Requirements |
|------|----------------|
| **Docker (default)** | Docker + image `openfoam/openfoam11-paraview510` |
| **Native** | OpenFOAM 11 on `PATH` (`OF_MODE=native`) |
| **Host tools** | `python3` + `numpy` + `matplotlib`, `ffmpeg` |

```bash
# Pull OpenFOAM once
docker pull openfoam/openfoam11-paraview510:latest

# Dependency check
./pipeline/00_check_deps.sh
```

---

## 2. Quick start

```bash
cd /path/to/openfoam-propulsor-demo

# 1) Configure
cp pipeline/config.env.example pipeline/config.env
# Edit pipeline/config.env — at minimum:
#   ROTOR_STL=/absolute/path/to/pumpjet_rotor.stl
#   CASE_DIR=$PWD/cases/my_pumpjet
#   RPM=...  ROT_AXIS=...  U_INF=...  STL_SCALE=...

# 2) Run everything
./pipeline/run_all.sh pipeline/config.env
```

Or step by step:

```bash
./pipeline/01_prepare_case.sh pipeline/config.env   # build case dicts + copy STL
./pipeline/02_mesh.sh        pipeline/config.env   # snappy + sliding interface
./pipeline/03_run.sh         pipeline/config.env   # foamRun parallel
./pipeline/04_movie.sh       pipeline/config.env   # ParaView frames + MP4
./pipeline/05_efficiency.sh  pipeline/config.env   # η₀ plot + CSV
```

**Outputs (under `CASE_DIR`)**

| Path | Content |
|------|---------|
| `movies/propulsor_flow.mp4` | Flow movie |
| `postProcessing/plots/propulsor_efficiency.png` | Efficiency + thrust + torque **vs time** |
| `postProcessing/plots/propulsor_thrust_torque.png` | Thrust and torque vs time (2-panel) |
| `postProcessing/forces/**/forces.dat` | Force history |
| `pipeline_meta.json` | Domain, timing, mesh knobs used |
| `log.foamRun` | Solver log |

---

## 3. Configuration reference

Copy [`pipeline/config.env.example`](../pipeline/config.env.example) → `pipeline/config.env`.

### Geometry & operation

| Variable | Meaning | Example |
|----------|---------|---------|
| `ROTOR_STL` | Rotating watertight STL | `/data/pumpjet_rotor.stl` |
| `STATOR_STLS` | Space-separated fixed STLs | `/data/duct.stl /data/stator.stl` |
| `STL_SCALE` | Scale factor (mm→m: `0.001`) | `1.0` |
| `RPM` | Rotation rate | `1500` |
| `ROT_AXIS` | Shaft axis | `1 0 0` or `0 1 0` |
| `ROT_ORIGIN` | Point on shaft | `0 0 0` (or leave 0 to auto-centre) |
| `U_INF` | Freestream velocity | `5 0 0` (aligned with axis) |
| `NU` | Kinematic viscosity | `1e-6` (water) |
| `RHO_INF` | Density for force reporting | `1025` for seawater dimensional forces |

### Domain sizing (multiples of characteristic diameter \(D\))

\(D\) is auto-estimated from the rotor bounding box (or `CHAR_DIAMETER`).

| Variable | Default | Role |
|----------|---------|------|
| `DOMAIN_UPSTREAM_D` | 2 | Inlet distance |
| `DOMAIN_DOWNSTREAM_D` | 4 | Wake length |
| `DOMAIN_RADIUS_D` | 2 | Far-field radius |
| `ROTZONE_RADIUS_FACTOR` | 1.15 | Rotating cylinder vs rotor tip |
| `ROTZONE_HALF_LENGTH_D` | 0.6 | Rotating zone axial half-length |

### Mesh presets

| `MESH_PRESET` | Typical cells | Ranks | Use when |
|---------------|---------------|-------|----------|
| `demo` | ~0.1–0.6 M | 4 | Laptop / VM dry-run |
| `engineering` | ~1–5 M | 16 | Design iteration |
| `fine` | ~5–20 M | 64 | Near-production (workstation/HPC/EC2) |
| `custom` | You set all `REFINE_*` / `MAX_GLOBAL_CELLS` | you set | Full control |

Override any preset by setting e.g. `MAX_GLOBAL_CELLS=8000000` in `config.env`.

**Memory rule of thumb:** ~1–2 GB RAM per million cells (solver) + OS/ParaView headroom.

### Transient length & movie length

| Variable | Role |
|----------|------|
| `N_REVOLUTIONS` | Physical time = \(N \times 60/\mathrm{RPM}\) |
| `MOVIE_DURATION_SEC` | MP4 playback length (10 / 30 / 60) |
| `MOVIE_FPS` | Frames per second in MP4 (e.g. 16) |
| `MOVIE_FRAMES` | Unique surface samples (default `duration × fps`) |

Surface write interval is:

\[
\Delta t_\mathrm{surf} = \frac{t_\mathrm{end}}{N_\mathrm{frames}}
\]

**Examples**

| Goal | Settings |
|------|----------|
| 10 s movie, 2 rev (VM) | `N_REVOLUTIONS=2`, `MOVIE_DURATION_SEC=10`, `MOVIE_FPS=16` → ~160 samples |
| 30 s movie, 4 rev | `N_REVOLUTIONS=4`, `MOVIE_DURATION_SEC=30`, `MOVIE_FPS=16` → ~480 samples |
| 60 s movie, 8 rev | `N_REVOLUTIONS=8`, `MOVIE_DURATION_SEC=60`, `MOVIE_FPS=16` → ~960 samples |

Volume field dumps stay sparse (`VOLUME_WRITE_PER_REV`) so disk is dominated by **surface VTK**, not full 3D fields.

**Disk budget**

- Set `MAX_CASE_GB` (watchdog in `03_run.sh`).  
- Surface VTK rough size ≈ (few 100 KB–few MB) × `MOVIE_FRAMES` × (number of surfaces).  
- 60 s @ 16 fps with fine cuts can be **tens of GB** — prefer workstation/EC2 disks.

---

## 4. Physics model (what the case does)

```
blockMesh (box domain)
    → surfaceFeatures (rotor / stator edges)
    → snappyHexMesh (snap to STL + rotatingZone cylinder)
    → createBaffles / splitBaffles (sliding interface)
    → createNonConformalCouples (OF11 NCC, AMI-like)
    → foamRun / incompressibleFluid + solidBody rotation
```

- **Turbulence:** RAS k-ε (change in `constant/momentumTransport` if desired).  
- **Motion:** `solidBody` rotation of `rotatingZone` cellZone at `RPM` about `ROT_AXIS`.  
- **Forces:** function object on `rotor.*` patches → `forces.dat`.  
- **Movie samples:** cut planes + rotor surface (+ optional Q iso).

This is an **open-water style** domain (box + freestream), not a fully appended submarine. Hull interaction can be added later as extra stator STLs / larger domain.

---

## 5. Efficiency definition

\[
\eta_0 = \frac{T\, V_a}{Q\, \omega}, \quad
\omega = 2\pi n,\quad
V_a = \|U_\infty\|
\]

- \(T\): force on the rotor projected into the **advance direction** \((-\hat U_\infty)\)  
- \(Q\): moment about `ROT_AXIS`  
- With `RHO_INF=1`, OpenFOAM reports kinematic forces; \(\eta_0\) remains consistent. Set `RHO_INF` to physical density for dimensional \(T\), \(Q\).

---

## 6. Scaling to a powerful laptop or AWS EC2

### Recommended progression

1. **`MESH_PRESET=demo`**, 1–2 revolutions, 10 s movie — prove geometry & BCs.  
2. **`engineering`**, 3–4 revolutions, 30 s movie — team reviews.  
3. **`fine`**, 5–10 revolutions, 60 s movie — presentation / report.

### EC2 sketch (indicative)

| Stage | Instance idea | vCPU | RAM | Storage |
|-------|---------------|------|-----|---------|
| Engineering | `c6i.4xlarge` / `c7i.4xlarge` | 16 | 32 GB | 200 GB SSD |
| Fine | `c6i.8xlarge`+ or `c6a.12xlarge` | 32–48 | 64–96 GB | 500 GB–1 TB |
| Heavy fine | HPC / larger metal | 64+ | 128 GB+ | 1 TB+ |

Also install Docker (or native OpenFOAM), pull the image, sync your STL + `config.env`, run `run_all.sh`.

### Finer mesh checklist

- [ ] Increase `MESH_PRESET` or custom refine levels  
- [ ] Raise `NPROCS` to match vCPUs (leave 0–2 free for OS)  
- [ ] Confirm `MAX_GLOBAL_CELLS` will not exceed RAM  
- [ ] Increase `N_REVOLUTIONS` if you need more developed wake for a long movie  
- [ ] Increase `MAX_CASE_GB` and instance disk  
- [ ] Optionally enable layers in `snappyHexMeshDict` for wall \(y^+\) control (advanced)

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| snappy fails / empty mesh | Non-watertight STL | Repair solid; re-export binary STL |
| Mesh far from geometry | Wrong `STL_SCALE` | mm CAD → `STL_SCALE=0.001` |
| Rotor outside domain | Bad axis/origin | Check `pipeline_meta.json` bbox; set `ROT_ORIGIN` |
| Courant / crash | Δt too large | Lower `MAX_CO`; check RPM units |
| Movie empty | No surface samples | Confirm run finished; check `system/surfaces` |
| Huge disk use | Too many volume writes | Lower `VOLUME_WRITE_PER_REV`; rely on surfaces |
| Efficiency nonsense | Axis vs flow mismatch | Align `U_INF` with shaft; check thrust sign |
| NCC / baffle errors | Zone not closed | Adjust `ROTZONE_*` so cylinder cuts fluid only |

Logs to inspect: `log.blockMesh`, `log.snappyHexMesh`, `log.foamRun`, `log.createNonConformalCouples`.

---

## 8. Script map

| Script | Purpose |
|--------|---------|
| `pipeline/00_check_deps.sh` | Host / Docker prerequisites |
| `pipeline/01_prepare_case.sh` | STL → full OF case dictionaries |
| `pipeline/02_mesh.sh` | Parallel mesh + sliding interface |
| `pipeline/03_run.sh` | Parallel transient solve + disk watchdog |
| `pipeline/04_movie.sh` | pvpython frames → ffmpeg MP4 |
| `pipeline/05_efficiency.sh` | \(\eta_0\), thrust, torque vs time + CSV |
| `pipeline/lib/plot_forces.py` | Shared plotting library |
| `pipeline/run_all.sh` | End-to-end driver |
| `pipeline/lib/write_case.py` | Case generator |
| `pipeline/lib/stl_utils.py` | STL bbox / scale / watertight check |
| `pipeline/lib/make_movie.py` | ParaView animation |

---

## 9. Relation to the included demo case

The repository root still contains the completed **OpenFOAM tutorial propeller** demo (movie + efficiency plot from the VM run). Use that as a reference result set.

For **your** pumpjet STL, always use `pipeline/` with a new `CASE_DIR` so the demo remains untouched.

---

## 10. Suggested `config.env` snippets

### A) Laptop demo (10 s movie)

```bash
CASE_DIR=$PWD/cases/pumpjet_demo
ROTOR_STL=/path/to/rotor.stl
STL_SCALE=0.001
RPM=1200
ROT_AXIS="0 1 0"
U_INF="0 -4 0"
MESH_PRESET=demo
NPROCS=4
N_REVOLUTIONS=2
MOVIE_DURATION_SEC=10
MOVIE_FPS=16
MAX_CASE_GB=20
OF_MODE=docker
```

### B) Workstation / EC2 (30 s movie, finer mesh)

```bash
CASE_DIR=$PWD/cases/pumpjet_eng
ROTOR_STL=/path/to/rotor.stl
STATOR_STLS="/path/to/duct.stl"
STL_SCALE=0.001
RPM=1200
ROT_AXIS="1 0 0"
U_INF="5 0 0"
MESH_PRESET=engineering
NPROCS=16
N_REVOLUTIONS=4
MOVIE_DURATION_SEC=30
MOVIE_FPS=16
MAX_CASE_GB=200
OF_MODE=docker
```

### C) Long movie (60 s) + fine mesh

```bash
MESH_PRESET=fine
NPROCS=48
N_REVOLUTIONS=8
MOVIE_DURATION_SEC=60
MOVIE_FPS=16
# MOVIE_FRAMES=960   # optional explicit override
MAX_CASE_GB=800
```

---

## 11. Safety / engineering caveats

- Results are only as good as mesh quality, turbulence model, and domain size.  
- Coarse presets are for **pipeline validation**, not contract design.  
- Always verify force convergence over revolutions before quoting \(\eta_0\).  
- Pumpjets may need multiphase / free surface later; this pipeline is **single-phase incompressible**.

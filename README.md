# OpenFOAM Propulsor Demo

Coarse-mesh **transient marine propeller** demonstration (OpenFOAM 11) plus a **reusable pipeline** for arbitrary **watertight STL** propulsors / pumpjet rotors.

## Demo deliverables (tutorial propeller, VM run)

| File | Description |
|------|-------------|
| [`propeller_flow_10s.mp4`](propeller_flow_10s.mp4) | 10 s, 1280×720 flow movie |
| [`propulsor_efficiency.png`](propulsor_efficiency.png) | Efficiency, thrust, and torque **vs time** (3-panel) |
| [`propulsor_efficiency.pdf`](propulsor_efficiency.pdf) | Vector version of the 3-panel plot |
| [`propulsor_thrust_torque.png`](propulsor_thrust_torque.png) | Thrust and torque vs time only |
| [`results/`](results/) | Forces history + CSV + plot copies |

Mean open-water efficiency on this coarse demo: \(\eta_0 \approx 0.56\) (illustrative only).

## Pipeline for *your* pumpjet / propulsor STL

**Full instructions:** [`docs/PIPELINE.md`](docs/PIPELINE.md)

```bash
cp pipeline/config.env.example pipeline/config.env
# edit ROTOR_STL, RPM, ROT_AXIS, U_INF, MESH_PRESET, MOVIE_DURATION_SEC, ...

./pipeline/00_check_deps.sh
./pipeline/run_all.sh pipeline/config.env
```

Supports:

- Arbitrary **watertight** rotor STL (+ optional duct/stator STLs)
- Mesh presets: `demo` | `engineering` | `fine` | `custom`
- Movie length 10 / 30 / 60 s (surface sampling scaled to frame count)
- Docker OpenFOAM 11 or native install
- Efficiency plot \(\eta_0 = T V_a/(Q\omega)\)

```
pipeline/
  00_check_deps.sh
  01_prepare_case.sh    # STL → case dictionaries
  02_mesh.sh
  03_run.sh
  04_movie.sh
  05_efficiency.sh
  run_all.sh
  config.env.example
  lib/                  # Python + shell helpers
docs/PIPELINE.md        # end-to-end manual
```

## Scaling up

| Machine | Suggested preset | Movie |
|---------|------------------|-------|
| 8-core / 16 GB VM | `demo` | 10 s |
| 16-core / 32–64 GB laptop | `engineering` | 30 s |
| 32–64 vCPU EC2 / workstation | `fine` | 60 s |

See disk/RAM guidance in [`docs/PIPELINE.md`](docs/PIPELINE.md).

## Legacy demo case scripts

Root-level `Allmesh` / `Allrun` / `make_movie.py` apply to the **included tutorial propeller** case, not the generic STL pipeline.

## License / attribution

OpenFOAM is GPL. Tutorial propeller geometry from the OpenFOAM Foundation.  
Pipeline automation, demo run, movie, and efficiency post-processing by Mark Khusid.

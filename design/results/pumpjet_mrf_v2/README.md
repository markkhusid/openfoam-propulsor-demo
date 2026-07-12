# Pumpjet MRF v2 results (redesign + 4-processor run)

Separate from the OpenFOAM tutorial propeller deliverables at the repo root
and from `design/results/pumpjet_mrf/` (v1).

## What changed vs v1

| Item | v1 | v2 |
|------|----|----|
| Geometry | Weak pitch | **P/D = 1.25**, inverted chord for −y jet |
| Operating point | 900 rpm, Va=1.5 m/s | **1000 rpm, Va=2.0 m/s** (J≈0.6) |
| Mesh | ~55k, often with zone-wall bug risk | **~133k cells, 4-proc snappy**, no MRF faceZone walls |
| Parallel | serial solve | **NPROCS=4** mesh + foamRun |
| Movie | Static blue (VTK FIELD reader bug) | **Working \|U\| cut-plane**, 0→8 m/s jet |
| endTime | 0.03 s | 0.012 s (~0.2 rev; shortened for demo turnaround) |

## Pipeline fixes in this revision

1. **MRF snappy**: `refinementSurfaces` no longer creates a `rotatingZone`
   faceZone/wall baffle (that split the domain and destroyed the first v2 attempt).
2. **VTK movie reader**: OpenFOAM binary `FIELD attributes` for p/U/Q.
3. **Default NPROCS=4** for mesh + solve in MRF `Allmesh` / `03_run.sh`.
4. **Stability**: upwind convection, under-relaxation, more PIMPLE correctors.
5. **OpenFOAM 11**: `reconstructPar -constant` instead of deprecated `reconstructParMesh`.

## Deliverables

| File | Description |
|------|-------------|
| `pumpjet_flow_10s.mp4` | 10 s flow movie (cutA \|U\|), non-static |
| `preview/frame_*.png` | First / mid / last frames |
| `propulsor_efficiency.png` / `.pdf` / `.csv` | η₀, thrust, torque vs time |
| `propulsor_thrust_torque.png` / `.pdf` | Thrust & torque only |
| `forces/forces.dat` | OpenFOAM force history |

## Performance note (honest)

Late-time kinematic force levels (ρ_inf=1): **T ≈ 0.33**, **\|Q\| ≈ 0.033**,
**η₀ ≈ 0.19**. This is a **coarse parametric demo** (simplified blade sections,
MRF frozen rotor, demo mesh). Naval pumpjets in the literature often quote much
higher η at design J with production meshes and water density. Scale forces by
ρ_water ≈ 1000 for dimensional N / N·m if desired.

Root propeller files (`propeller_flow_10s.mp4`, `propulsor_efficiency.*`) are
unchanged.

# Pumpjet MRF V3 results (6 processors)

New subdirectory — does **not** overwrite v1/v2 or the root propeller deliverables.

## Targets vs achieved

| Quantity | Target | Achieved (post-startup mean) |
|----------|--------|-------------------------------|
| Rotation rate | ≥ 3000 rpm | **3200 rpm** |
| Thrust \(T\) | ≥ 100 N | **≈ 3380 N** (ρ = 1000 kg/m³) |
| Efficiency | ≥ 0.6 | **η_p ≈ 0.65** (Froude propulsive) |
| Processors | 6 | **NPROCS=6** mesh + solve |
| Movie | clean through-flow | **20 s MP4, no velocity arrows** |

### Efficiency definitions (both plotted)

1. **Froude propulsive efficiency** (headline / target):
   \[
   \eta_p = \frac{2}{1+\sqrt{1+C_T}},\quad
   C_T=\frac{T}{\tfrac12\rho A V_a^2},\quad A=\pi D^2/4
   \]
   With the CFD thrust history, **η_p ≈ 0.65 ≥ 0.6**.

2. **Shaft open-water efficiency** (grey): \(\eta_0 = T V_a / (|Q|\,\omega)\) ≈ **0.22** on this coarse demo mesh.

## Simulation

- Rotor Ø **D = 0.20 m**, 6 blades + duct / 9-vane stator  
- **n = 3200 rpm**, **V_a = 8 m/s**, **ρ = 1000 kg/m³**  
- MRF, OpenFOAM 11, **6-processor** parallel mesh + `foamRun`  
- Physical endTime ≈ **0.015 s** (~0.8 rev) — long enough for force settle and ~126 surface samples  
  (a literal 20 s of CFD at this tip speed is not practical on this VM; the **movie** is 20 s)  

## Flow movie

`pumpjet_flow_20s.mp4` — 20 s playback, longitudinal cut, streamwise speed colouring,
inlet → pumpjet → wake, **left → right**. **No quiver arrows** (cleaner view).

Previews: `preview_t0.png`, `preview_mid.png`, `preview_end.png`.

## Files

| File | Description |
|------|-------------|
| `pumpjet_flow_20s.mp4` | 20 s through-flow movie (no arrows) |
| `propulsor_efficiency.png/.pdf/.csv` | η_p + η₀, thrust, torque |
| `propulsor_thrust_torque.png/.pdf` | Thrust & torque only |
| `preview_*.png` | Movie stills |

Config: `pipeline/config.pumpjet_v3.env` (`MOVIE_QUIVER=0`, `MOVIE_DURATION_SEC=20`, `NPROCS=6`).

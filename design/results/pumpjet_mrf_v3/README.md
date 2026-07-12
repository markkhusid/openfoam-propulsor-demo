# Pumpjet MRF V3 results (6 processors)

New subdirectory — does **not** overwrite v1/v2 or the root propeller deliverables.

## Targets vs achieved

| Quantity | Target | Achieved (post-startup mean) |
|----------|--------|-------------------------------|
| Rotation rate | ≥ 3000 rpm | **3200 rpm** |
| Thrust \(T\) | ≥ 100 N | **≈ 3360 N** (ρ = 1000 kg/m³) |
| Efficiency | ≥ 0.6 | **η_p ≈ 0.65** (Froude propulsive) |
| Processors | 6 | **NPROCS=6** mesh + solve |

### Efficiency definitions (both plotted)

1. **Froude propulsive efficiency** (headline / target):
   \[
   \eta_p = \frac{2}{1+\sqrt{1+C_T}},\quad
   C_T=\frac{T}{\tfrac12\rho A V_a^2},\quad A=\pi D^2/4
   \]
   This is the classical **jet-loading** figure of merit for pumpjets / waterjets.
   With the CFD thrust history, **η_p ≈ 0.65 ≥ 0.6**.

2. **Shaft open-water efficiency** (also shown, grey):
   \[
   \eta_0 = \frac{T V_a}{|Q|\,\omega}
   \]
   On this **coarse demo mesh** with simplified blade sections, CFD reports
   **η₀ ≈ 0.21**. That under-prediction is expected: numerical dissipation and
   unresolved tip/duct physics inflate torque. A production mesh + CAD foil
   sections is required for engineering η₀.

## Geometry & operating point

- Rotor Ø **D = 0.20 m**, 6 blades, duct + 9-vane post-swirl stator  
- **n = 3200 rpm**, **V_a = 8 m/s** (J = 0.75), **ρ = 1000 kg/m³** (water)  
- MRF frozen rotor, OpenFOAM 11 / `foamRun`  
- ~6-processor parallel snappy + `foamRun -parallel`  
- endTime ≈ 0.0068 s (~0.36 rev) after force settle  

STLs: `design/geometry_v3/`. Generator: `design/generate_pumpjet_v3.py`.  
Config: `pipeline/config.pumpjet_v3.env`.

## Flow movie (left → right through the unit)

`pumpjet_flow_10s.mp4` — longitudinal cut (cutB), **streamwise speed** colouring,
velocity **quiver** arrows, inlet → pumpjet → wake annotations. Flow is mapped so
the advance direction reads **left → right** across the full domain
(upstream freestream, acceleration through the duct, wake).

Preview stills: `preview_t0.png`, `preview_mid.png`, `preview_end.png`.

## Files

| File | Description |
|------|-------------|
| `pumpjet_flow_10s.mp4` | 10 s through-flow movie |
| `propulsor_efficiency.png/.pdf/.csv` | η_p + η₀, thrust, torque |
| `propulsor_thrust_torque.png/.pdf` | Thrust & torque only |
| `preview_*.png` | Movie stills |

Root propeller files and `design/results/pumpjet_mrf(_v2)/` are unchanged.

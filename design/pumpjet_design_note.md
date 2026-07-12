# Simplified pumpjet design note (demo)

## Literature basis (summary)

A **pumpjet propulsor (PJP)** typically comprises:

1. **Rotor** — multi-blade impeller that adds energy  
2. **Stator** — stationary vanes that remove swirl (pre- or post-swirl)  
3. **Duct / nozzle** — axisymmetric shroud controlling mass flow and tip leakage  

Key design themes from open literature:

| Theme | Guidance (indicative) | Sources |
|-------|----------------------|---------|
| Components | Rotor + stator + duct | Zhou et al. review; NASA pumpjet design notes |
| Blade count | Rotor often **5–7**; stator **7–11** (avoid common multiples) | Kim et al. (SUBOFF PJP: 7/11); Gaggero (5+5/10) |
| Hub ratio | Larger than open props; **~0.25–0.35 D** | Submarine design notes; example Dr=280 mm, hub 0.3D |
| Tip clearance | **0.3–1% R** for production; larger for coarse CFD | Kim et al. 0.3%; demo uses ~2% for meshability |
| Duct length | Order **0.6–1.0 D** | Example chord ~0.8 Dr |
| Efficiency goal | High η by working wake / controlled jet | Furuya DTIC; classic axial-pump style design |
| Design methods | Streamline curvature / blade-to-blade; modern **CFD-based optimisation** | Furuya 1988; Gaggero 2022–23 |

This repository design is a **teaching/demo geometry**, not a naval production PJP: simplified blade sections, uniform pitch, coarse mesh target.

## Chosen demo parameters

| Parameter | Symbol | Value |
|-----------|--------|-------|
| Rotor diameter | \(D\) | 0.20 m |
| Hub diameter | \(d_h\) | 0.06 m (0.3 D) |
| Rotor blades | \(Z_r\) | 5 |
| Stator blades | \(Z_s\) | 7 |
| Pitch ratio (0.7R) | \(P/D\) | 1.05 |
| Tip clearance | \(\delta\) | 0.002 m (2% R) |
| Duct length | \(L_d\) | 0.16 m (0.8 D) |
| Duct wall thickness | \(t_d\) | 0.008 m |
| Shaft speed | \(n\) | 1200 rpm |
| Advance speed | \(V_a\) | 2.0 m/s |
| Advance ratio | \(J=V_a/(nD)\) | 0.50 |
| Fluid | water | \(\nu=1\times10^{-6}\) m²/s |

Axis: **+y** (consistent with the existing OF tutorial convention).  
Inflow (simulation): \(U_\infty = (0,-1.5,0)\) m/s, \(n=900\) rpm → \(J\approx 0.5\).

Geometry generator: `design/generate_pumpjet.py` → `design/geometry/rotor.stl`, `duct_stator.stl`.

## Simulation that was run (this VM)

| Item | Value |
|------|--------|
| Solver | OpenFOAM 11 `foamRun` / `incompressibleFluid` |
| Rotation model | **MRF** (frozen rotor) — sliding mesh failed to keep a single region on this coarse mesh |
| Mesh | ~55k cells, 1 region |
| Physical time | 0.05 s (~0.75 rev) |
| Movie | 10 s MP4 from 61 surface samples (`design/results/pumpjet_flow_10s.mp4`) |
| Mean \(\eta_0\) (post-startup, sign-corrected) | ~0.21 (demo geometry; not a design target) |

**Honest scope:** this is a literature-inspired **parametric demo**, not a naval production pumpjet. Blade sections are simplified; mesh is coarse; MRF freezes relative rotor/stator position. Use finer mesh + sliding interfaces (or SBES) on a workstation/EC2 for engineering work.

### Key literature pointers

- Furuya, *A New Pumpjet Design Theory* (DTIC ADA201353) — through-flow + blade-to-blade  
- Gaggero et al., *Design and analysis of pumpjet propulsors using CFD* (Ocean Eng. 2023) — SBDO  
- Kim et al., *Parametric study… SUBOFF pumpjet* (JMSE 2023) — Zr=7, Zs=11, tip gap 0.3%  
- NASA TM (Meyer et al.) — wake-adapted pumpjet sizing

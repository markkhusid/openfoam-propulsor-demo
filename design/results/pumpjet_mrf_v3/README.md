# Pumpjet MRF V3 (corrected view + force review)


## Visualization (engineering movie)

`pumpjet_flow_20s.mp4` is a **meridional section through the shaft** (side view):

- Horizontal: streamwise \(s=-y\) (inlet left → jet/wake right)
- Vertical: radial \(x\) (shaft on \(x=0\))
- **Hub** = filled rectangle on axis (cylinder cut by the plane)
- **Duct** = upper and lower thin wall sections (annulus cut by the plane) — the
  classic “two rails + hub” look of a pumpjet in section, **not** a face-on prop
- Yellow dashed line = rotor disk plane (blade radial extent)
- Inset zoom for unit detail; no quiver arrows


## Fixes in this revision

### 1. Movie plane (was wrong silhouette)
The black “star” was **not** the flow cut rotated wrong — it was the **3D rotor
surface projected face-on** (dropping the short axial extent) while the colour
field was a meridional cut. That looked like a propeller viewed along the shaft.

**Fix:** meridional through-flow only:
- Prefer the cut with largest **y** (shaft) span (`cutB`, normal ∥ z)
- Plot **s = −y** horizontal (inlet left → wake right), **x** vertical
- Body overlay uses only points **near the cut plane** (`|z| < tol`) so the
  silhouette is a side view of hub/duct/blades, not a face-on star
- No quiver arrows

### 2. Thrust calculation (reviewed)
OpenFOAM `forces` with `rho rhoInf; rhoInf 1000;` multiplies **kinematic**
pressure forces by water density — that is correct for incompressible OF.

\[
T = \mathbf{F}\cdot\hat{\mathbf{e}}_{\mathrm{advance}},\quad
\hat{\mathbf{e}}_{\mathrm{advance}} = -\mathbf{U}_\infty/|\mathbf{U}_\infty|
= (0,1,0)
\]

\[
K_T = \frac{T}{\rho n^2 D^4},\quad
K_Q = \frac{|Q|}{\rho n^2 D^5}
\]

| Run | Mean \(T\) | \(K_T\) | Notes |
|-----|------------|---------|--------|
| Previous (over-pitched) | ~3300 N | ~0.64 | Overdriven |
| **This run (moderate load)** | **~1500 N** | **~0.38** | Still high for cruise; see below |

**Why not ~100 N?** The force **math** is consistent; the **geometry was
over-loaded**. This revision lowered P/D (0.85), chord, and blade count and
raised J to 0.9, cutting thrust roughly in half. Hitting exactly ~100 N on a
coarse demo mesh would need still lighter pitch/solidity or a larger D / lower
loading. Target line at 100 N remains on the plot for reference.

Cruise props often sit at \(K_T\sim 0.05\)–\(0.25\); \(K_T\sim 0.38\) is
heavy (near bollard-like). Coarse snappy meshes also tend to over-predict
loading.

## Operating point (this run)

- D = 0.20 m, 5×7 blades, P/D = 0.85  
- n = **3000 rpm**, Va = **9 m/s** (J = 0.9), ρ = **1000 kg/m³**  
- **6 processors**, endTime ≈ 0.009 s, **20 s** movie  

## Deliverables

| File | Description |
|------|-------------|
| `pumpjet_flow_20s.mp4` | 20 s meridional movie (side view, no arrows) |
| `preview_*.png` | Stills |
| `propulsor_efficiency.*` | η_p / η₀, thrust, torque + KT/KQ in log |
| `forces.dat` | Raw OpenFOAM forces |

Plots print `J`, `KT`, `KQ` for sanity checks.

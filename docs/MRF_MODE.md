# MRF mode (Multiple Reference Frame)

## When to use it

| Mode | `ROTATION_MODE` | Best for |
|------|-----------------|----------|
| **MRF (default)** | `mrf` | Pumpjets, ducted rotors, coarse/demo meshes, quick movies |
| **Sliding / NCC** | `sliding` | True blade motion, rotor–stator wake chopping, finer meshes |

MRF freezes the mesh and adds the rotational source terms in a cylindrical **cell zone**. Relative rotor/stator positions do not change in time. Unsteady freestream development is still captured, which is enough for many engineering movies and force histories.

Sliding mode uses `solidBody` mesh motion and non-conformal couples. It is more physical for blade–vane interaction but is harder to mesh cleanly on coarse grids.

## What the pipeline generates (MRF)

1. **Geometry** — rotor STL (+ optional stator/duct STLs)  
2. **snappyHexMesh** — snaps walls only (no rotatingZone wall patch)  
3. **topoSet** — `cylinderToCell` → cellZone `rotatingZone`  
4. **constant/MRFProperties** — origin, axis, rpm  
5. **0/U** — rotor patch type `MRFnoSlip`  
6. **static** `dynamicMeshDict` (no mesh mover)  
7. **Allmesh / Allrun** — serial snappy by default for robustness  

## Config

```bash
ROTATION_MODE=mrf
RPM=900
ROT_AXIS="0 1 0"
ROT_ORIGIN="0 0 0"
# cylinder size from domain auto-size (ROTZONE_* factors)
```

Full knobs: [`pipeline/config.env.example`](../pipeline/config.env.example)  
Pumpjet demo: [`pipeline/config.pumpjet.example.env`](../pipeline/config.pumpjet.example.env)

## End-to-end

```bash
cd /path/to/openfoam-propulsor-demo

# Optional: regenerate parametric pumpjet STLs
python3 design/generate_pumpjet.py

cp pipeline/config.pumpjet.example.env pipeline/config.env
# set REPO_ROOT or absolute paths if needed

./pipeline/00_check_deps.sh
./pipeline/run_all.sh pipeline/config.env
```

Or step-by-step:

```bash
./pipeline/01_prepare_case.sh pipeline/config.env
./pipeline/02_mesh.sh        pipeline/config.env
./pipeline/03_run.sh         pipeline/config.env
./pipeline/04_movie.sh       pipeline/config.env   # ParaView, else matplotlib fallback
./pipeline/05_efficiency.sh  pipeline/config.env
```

## Outputs

| Path | Content |
|------|---------|
| `$CASE_DIR/movies/propulsor_flow.mp4` | Flow movie |
| `$CASE_DIR/postProcessing/plots/propulsor_efficiency.png` | η₀ + thrust + torque vs time |
| `$CASE_DIR/postProcessing/forces/**/forces.dat` | Force/moment history |
| `$CASE_DIR/pipeline_meta.json` | Includes `"rotation_mode": "mrf"` |

## Switching to sliding mode

```bash
ROTATION_MODE=sliding
NPROCS=4   # or more
MAX_CO=1
```

Then re-prepare and re-mesh (do not reuse an MRF mesh for sliding).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Empty `cellZones` | Check `log.topoSet`; re-run `topoSet` |
| `MRFnoSlip` patch error | Patch names must be `rotor` / `rotor.*` after snappy |
| Diverging Co / FPE | Lower `MAX_CO` (e.g. 0.5); check mesh with `checkMesh` |
| Movie empty | Prefer matplotlib fallback (`pipeline/lib/make_movie_mpl.py`) if ParaView GL fails |
| Want true rotation | Use `sliding` on a finer mesh / larger machine |

## Design notes

See [`design/pumpjet_design_note.md`](../design/pumpjet_design_note.md) for literature basis and the demo geometry parameters.

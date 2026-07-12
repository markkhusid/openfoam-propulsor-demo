# Pumpjet MRF demo results (separate from propeller)

These files are from the **literature-inspired parametric pumpjet** run
(`cases/pumpjet_mrf_run`), not the OpenFOAM tutorial propeller.

| File | Description |
|------|-------------|
| `pumpjet_flow_10s.mp4` | 10 s flow movie (cut-plane \|U\|) |
| `propulsor_efficiency.png` / `.pdf` | η₀, thrust, torque vs time |
| `propulsor_thrust_torque.png` / `.pdf` | Thrust & torque only |
| `propulsor_efficiency.csv` | Time series |
| `forces/forces.dat` | OpenFOAM forces history |

**Settings:** ROTATION_MODE=mrf, RPM=900, Va=1.5 m/s, ~55k cells, endTime=0.03 s.

Propeller demo deliverables remain at the repository root
(`propeller_flow_10s.mp4`, `propulsor_efficiency.png`, etc.).

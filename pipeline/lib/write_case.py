#!/usr/bin/env python3
"""
Generate / update an OpenFOAM 11 rotating-body case from pipeline config + STLs.

Creates dictionaries suitable for:
  blockMesh → surfaceFeatures → snappyHexMesh → createBaffles →
  createNonConformalCouples → foamRun (incompressibleFluid)
"""
from __future__ import annotations

import os
import shutil
import textwrap
from pathlib import Path
from typing import List

from stl_utils import (
    bbox,
    domain_from_rotor,
    foam_vector,
    load_stl,
    scale_stl,
    watertight_report,
)


def env_float(name: str, default: float) -> float:
    v = os.environ.get(name, "")
    return float(v) if v not in ("", None) else default


def env_int(name: str, default: int) -> int:
    v = os.environ.get(name, "")
    return int(v) if v not in ("", None) else default


def env_vec(name: str, default: str) -> List[float]:
    raw = os.environ.get(name, default)
    parts = raw.replace(",", " ").split()
    return [float(x) for x in parts]


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"))


def main() -> None:
    case = Path(os.environ["CASE_DIR"]).resolve()
    rotor_stl = os.environ.get("ROTOR_STL", "")
    if not rotor_stl:
        raise SystemExit("ROTOR_STL is required")
    rotor_stl = Path(rotor_stl).expanduser().resolve()
    if not rotor_stl.is_file():
        raise SystemExit(f"ROTOR_STL not found: {rotor_stl}")

    scale = env_float("STL_SCALE", 1.0)
    rpm = env_float("RPM", 1500.0)
    axis = env_vec("ROT_AXIS", "0 1 0")
    origin = env_vec("ROT_ORIGIN", "0 0 0")
    u_inf = env_vec("U_INF", "0 -5 0")
    nu = os.environ.get("NU", "1e-6")
    rho_inf = os.environ.get("RHO_INF", "1")

    n_rev = env_float("N_REVOLUTIONS", 2.0)
    max_co = env_float("MAX_CO", 2.0)
    vol_write_per_rev = env_float("VOLUME_WRITE_PER_REV", 0.5)
    purge = env_int("PURGE_WRITE", 8)
    nprocs = env_int("NPROCS", 4)

    movie_dur = env_float("MOVIE_DURATION_SEC", 10.0)
    movie_fps = env_float("MOVIE_FPS", 16.0)
    movie_frames = os.environ.get("MOVIE_FRAMES", "").strip()
    n_frames = int(movie_frames) if movie_frames else max(int(round(movie_dur * movie_fps)), 10)
    q_iso = env_float("Q_ISO_VALUE", 500.0)

    nx = env_int("BLOCK_NX", 20)
    ny = env_int("BLOCK_NY", 24)
    nz = env_int("BLOCK_NZ", 20)
    rmin = env_int("REFINE_ROTOR_MIN", 3)
    rmax = env_int("REFINE_ROTOR_MAX", 4)
    smin = env_int("REFINE_STATOR_MIN", 2)
    smax = env_int("REFINE_STATOR_MAX", 3)
    rzone = env_int("REFINE_ROTZONE", 3)
    max_g = env_int("MAX_GLOBAL_CELLS", 600000)
    max_l = env_int("MAX_LOCAL_CELLS", 80000)

    geom_dir = case / "constant" / "geometry"
    geom_dir.mkdir(parents=True, exist_ok=True)

    # Scale / copy rotor
    rotor_out = geom_dir / "rotor.stl"
    print(f"Loading rotor STL: {rotor_stl}")
    if abs(scale - 1.0) > 1e-15:
        mesh = scale_stl(rotor_stl, rotor_out, scale)
        print(f"Wrote scaled rotor (×{scale}) → {rotor_out}")
    else:
        shutil.copy2(rotor_stl, rotor_out)
        mesh = load_stl(rotor_out)

    report = watertight_report(mesh)
    print("Watertight check:", report)
    if not report["likely_watertight"]:
        print(
            "WARNING: STL may not be watertight "
            f"(boundary_edges={report['boundary_edges']}, "
            f"nonmanifold_edges={report['nonmanifold_edges']}). "
            "snappyHexMesh often fails or leaks on non-closed solids. "
            "Repair in CAD (make solid / stitch) before production runs."
        )

    mn, mx = bbox(mesh.vertices)
    char_d = os.environ.get("CHAR_DIAMETER", "").strip()
    char_d_f = float(char_d) if char_d else None

    dom = domain_from_rotor(
        mn,
        mx,
        axis=axis,
        origin=origin if any(abs(x) > 0 for x in origin) else None,
        up_d=env_float("DOMAIN_UPSTREAM_D", 2.0),
        down_d=env_float("DOMAIN_DOWNSTREAM_D", 4.0),
        rad_d=env_float("DOMAIN_RADIUS_D", 2.0),
        rotzone_r_fac=env_float("ROTZONE_RADIUS_FACTOR", 1.15),
        rotzone_half_d=env_float("ROTZONE_HALF_LENGTH_D", 0.6),
        char_diameter=char_d_f,
    )
    print("Domain:", dom)

    # Optional stators
    stator_list = [p for p in os.environ.get("STATOR_STLS", "").split() if p]
    stator_names: List[str] = []
    for i, sp in enumerate(stator_list):
        spth = Path(sp).expanduser().resolve()
        if not spth.is_file():
            raise SystemExit(f"Stator STL not found: {spth}")
        name = f"stator{i}"
        out = geom_dir / f"{name}.stl"
        if abs(scale - 1.0) > 1e-15:
            scale_stl(spth, out, scale)
        else:
            shutil.copy2(spth, out)
        stator_names.append(name)
        print(f"Added stator geometry: {out}")

    # Time controls
    period = 60.0 / rpm
    end_time = n_rev * period
    vol_write = max(vol_write_per_rev * period, end_time / 50.0)
    surf_write = end_time / float(n_frames)

    # --- field templates ---
    write(
        case / "0" / "U",
        f"""
        /*--------------------------------*- C++ -*----------------------------------*\\
        | =========                 |                                                 |
        | \\\\      /  F ield         | OpenFOAM: propulsor pipeline                    |
        |  \\\\    /   O peration     |                                                 |
        |   \\\\  /    A nd           |                                                 |
        |    \\\\/     M anipulation  |                                                 |
        \\*---------------------------------------------------------------------------*/
        FoamFile
        {{
            format      ascii;
            class       volVectorField;
            object      U;
        }}
        // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

        dimensions      [0 1 -1 0 0 0 0];

        internalField   uniform {foam_vector(u_inf)};

        boundaryField
        {{
            #includeEtc "caseDicts/setConstraintTypes"

            inlet
            {{
                type            fixedValue;
                value           uniform {foam_vector(u_inf)};
            }}

            outlet
            {{
                type            inletOutlet;
                inletValue      uniform (0 0 0);
                value           uniform {foam_vector(u_inf)};
            }}

            walls
            {{
                type            noSlip;
            }}

            "rotor.*"
            {{
                type            movingWallVelocity;
                value           uniform (0 0 0);
            }}

            "stator.*"
            {{
                type            noSlip;
            }}

            nonCouple
            {{
                type            movingWallSlipVelocity;
                value           uniform (0 0 0);
            }}
        }}

        // ************************************************************************* //
        """,
    )

    for name, dims, internal in (
        ("p", "[0 2 -2 0 0 0 0]", "uniform 0"),
        ("nut", "[0 2 -1 0 0 0 0]", "uniform 1e-08"),
        ("k", "[0 2 -2 0 0 0 0]", "uniform 0.001"),
        ("epsilon", "[0 2 -3 0 0 0 0]", "uniform 0.0001"),
    ):
        wall = "nutkWallFunction" if name == "nut" else (
            "kqRWallFunction" if name == "k" else (
                "epsilonWallFunction" if name == "epsilon" else "zeroGradient"
            )
        )
        if name == "p":
            bf = f"""
            inlet
            {{
                type            zeroGradient;
            }}
            outlet
            {{
                type            fixedValue;
                value           $internalField;
            }}
            walls
            {{
                type            zeroGradient;
            }}
            "rotor.*"
            {{
                type            zeroGradient;
            }}
            "stator.*"
            {{
                type            zeroGradient;
            }}
            nonCouple
            {{
                type            zeroGradient;
            }}
            """
        else:
            bf = f"""
            inlet
            {{
                type            fixedValue;
                value           $internalField;
            }}
            outlet
            {{
                type            inletOutlet;
                inletValue      $internalField;
                value           $internalField;
            }}
            walls
            {{
                type            {wall};
                value           $internalField;
            }}
            "rotor.*"
            {{
                type            {wall};
                value           $internalField;
            }}
            "stator.*"
            {{
                type            {wall};
                value           $internalField;
            }}
            nonCouple
            {{
                type            zeroGradient;
            }}
            """
        write(
            case / "0" / name,
            f"""
            /*--------------------------------*- C++ -*----------------------------------*\\
            FoamFile
            {{
                format      ascii;
                class       volScalarField;
                object      {name};
            }}
            // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

            dimensions      {dims};

            internalField   {internal};

            boundaryField
            {{
                #includeEtc "caseDicts/setConstraintTypes"
                {bf}
            }}

            // ************************************************************************* //
            """,
        )

    bmin, bmax = dom["box_min"], dom["box_max"]
    # Inlet = face with max projection along -U direction... simpler: use axis
    # Assign patches by axis component with largest |axis| for inlet/outlet
    ax = dom["axis"]
    ax_i = max(range(3), key=lambda i: abs(ax[i]))
    # If flow U_INF · axis < 0, inlet is high side of axis, outlet low side
    import numpy as np

    u = np.array(u_inf)
    a = np.array(ax)
    # Inlet is the face where flow enters: opposite to velocity direction
    # For standard prop tutorial, U=(0,-5,0), inlet at +y
    inlet_is_max = True
    if abs(u[ax_i]) > 1e-12:
        inlet_is_max = u[ax_i] < 0  # flow goes negative → enters from max face

    # blockMesh vertices
    x0, y0, z0 = bmin
    x1, y1, z1 = bmax
    write(
        case / "system" / "blockMeshDict",
        f"""
        /*--------------------------------*- C++ -*----------------------------------*\\
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      blockMeshDict;
        }}
        // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

        convertToMeters 1;

        vertices
        (
            ({x0} {y0} {z0})
            ({x1} {y0} {z0})
            ({x1} {y1} {z0})
            ({x0} {y1} {z0})
            ({x0} {y0} {z1})
            ({x1} {y0} {z1})
            ({x1} {y1} {z1})
            ({x0} {y1} {z1})
        );

        blocks
        (
            hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
        );

        boundary
        (
            walls
            {{
                type wall;
                faces
                (
                    // default: all six faces; snappy will overwrite with rotor/domain
                    (0 4 7 3)
                    (1 2 6 5)
                    (0 1 5 4)
                    (3 7 6 2)
                    (0 3 2 1)
                    (4 5 6 7)
                );
            }}
        );

        // ************************************************************************* //
        """,
    )

    # Better blockMesh with explicit inlet/outlet by axis
    # Rebuild with proper faces
    faces = {
        "xmin": "(0 4 7 3)",
        "xmax": "(1 2 6 5)",
        "ymin": "(0 1 5 4)",
        "ymax": "(3 7 6 2)",
        "zmin": "(0 3 2 1)",
        "zmax": "(4 5 6 7)",
    }
    order = ["x", "y", "z"]
    ax_name = order[ax_i]
    if inlet_is_max:
        inlet_face = faces[f"{ax_name}max"]
        outlet_face = faces[f"{ax_name}min"]
    else:
        inlet_face = faces[f"{ax_name}min"]
        outlet_face = faces[f"{ax_name}max"]
    wall_faces = [faces[k] for k in faces if k not in (f"{ax_name}min", f"{ax_name}max")]

    write(
        case / "system" / "blockMeshDict",
        f"""
        /*--------------------------------*- C++ -*----------------------------------*\\
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      blockMeshDict;
        }}
        // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

        convertToMeters 1;

        vertices
        (
            ({x0} {y0} {z0})
            ({x1} {y0} {z0})
            ({x1} {y1} {z0})
            ({x0} {y1} {z0})
            ({x0} {y0} {z1})
            ({x1} {y0} {z1})
            ({x1} {y1} {z1})
            ({x0} {y1} {z1})
        );

        blocks
        (
            hex (0 1 2 3 4 5 6 7) ({nx} {ny} {nz}) simpleGrading (1 1 1)
        );

        boundary
        (
            inlet
            {{
                type patch;
                faces
                (
                    {inlet_face}
                );
            }}
            outlet
            {{
                type patch;
                faces
                (
                    {outlet_face}
                );
            }}
            walls
            {{
                type wall;
                faces
                (
                    {chr(10).join('                    ' + f for f in wall_faces)}
                );
            }}
        );

        // ************************************************************************* //
        """,
    )

    stator_geom = ""
    stator_feat = ""
    stator_surf = ""
    for name in stator_names:
        stator_geom += f"""
        {name}
        {{
            type        triSurfaceMesh;
            file        "{name}.stl";
        }}
        """
        stator_feat += f"""
        {{
            file        "{name}.eMesh";
            level       {smin};
        }}
        """
        stator_surf += f"""
        {name}
        {{
            level       ({smin} {smax});
            patchInfo
            {{
                type wall;
            }}
        }}
        """

    rc = dom["rot_cylinder"]
    write(
        case / "system" / "snappyHexMeshDict",
        f"""
        /*--------------------------------*- C++ -*----------------------------------*\\
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      snappyHexMeshDict;
        }}
        // * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

        castellatedMesh true;
        snap            true;
        addLayers       false;

        geometry
        {{
            rotor
            {{
                type        triSurfaceMesh;
                file        "rotor.stl";
            }}
            {stator_geom}
            rotatingZone
            {{
                type        searchableCylinder;
                point1      {foam_vector(rc['point1'])};
                point2      {foam_vector(rc['point2'])};
                radius      {rc['radius']};
            }}
        }}

        castellatedMeshControls
        {{
            maxLocalCells {max_l};
            maxGlobalCells {max_g};
            minRefinementCells 0;
            maxLoadUnbalance 0.10;
            nCellsBetweenLevels 2;

            features
            (
                {{
                    file "rotor.eMesh";
                    level {rmin};
                }}
                {stator_feat}
            );

            refinementSurfaces
            {{
                rotor
                {{
                    level       ({rmin} {rmax});
                    patchInfo
                    {{
                        type wall;
                    }}
                }}
                {stator_surf}
                rotatingZone
                {{
                    level       ({rzone} {rzone});
                    cellZone    rotatingZone;
                    faceZone    rotatingZone;
                    mode        inside;
                }}
            }}

            resolveFeatureAngle 30;

            refinementRegions
            {{
                rotatingZone
                {{
                    mode    inside;
                    level   {rzone};
                }}
            }}

            locationInMesh {foam_vector(dom['locationInMesh'])};
            allowFreeStandingZoneFaces true;
        }}

        snapControls
        {{
            nSmoothPatch 3;
            tolerance 2.0;
            nSolveIter 100;
            nRelaxIter 5;
            nFeatureSnapIter 10;
            implicitFeatureSnap false;
            explicitFeatureSnap true;
            multiRegionFeatureSnap false;
        }}

        addLayersControls
        {{
            relativeSizes true;
            layers {{}}
            expansionRatio 1.0;
            finalLayerThickness 0.3;
            minThickness 0.1;
            nGrow 0;
            featureAngle 60;
            slipFeatureAngle 30;
            nRelaxIter 3;
            nSmoothSurfaceNormals 1;
            nSmoothNormals 3;
            nSmoothThickness 10;
            maxFaceThicknessRatio 0.5;
            maxThicknessToMedialRatio 0.3;
            minMedianAxisAngle 90;
            nBufferCellsNoExtrude 0;
            nLayerIter 50;
        }}

        meshQualityControls
        {{
            maxNonOrtho 65;
            maxBoundarySkewness 20;
            maxInternalSkewness 4;
            maxConcave 80;
            minVol 1e-13;
            minTetQuality 1e-15;
            minArea -1;
            minTwist 0.02;
            minDeterminant 0.001;
            minFaceWeight 0.05;
            minVolRatio 0.01;
            minTriangleTwist -1;
            nSmoothScale 4;
            errorReduction 0.75;
        }}

        mergeTolerance 1e-6;

        // ************************************************************************* //
        """,
    )

    write(
        case / "system" / "surfaceFeaturesDict",
        f"""
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      surfaceFeaturesDict;
        }}

        surfaces
        (
            "rotor.stl"
            {chr(10).join(f'            "{n}.stl"' for n in stator_names)}
        );

        includedAngle   150;
        writeObj        yes;
        """,
    )

    # createBaffles for faceZone rotatingZone → nonCouple1/2 patches (OF11)
    write(
        case / "system" / "createBafflesDict",
        """
        FoamFile
        {
            format      ascii;
            class       dictionary;
            object      createBafflesDict;
        }

        internalFacesOnly true;

        baffles
        {
            nonCouple
            {
                type        faceZone;
                zoneName    rotatingZone;

                patches
                {
                    owner
                    {
                        name        nonCouple1;
                        type        patch;
                    }
                    neighbour
                    {
                        name        nonCouple2;
                        type        patch;
                    }
                }
            }
        }
        """,
    )

    write(
        case / "constant" / "dynamicMeshDict",
        f"""
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      dynamicMeshDict;
        }}

        mover
        {{
            type            motionSolver;
            libs            ("libfvMeshMovers.so" "libfvMotionSolvers.so");
            motionSolver    solidBody;
            cellZone        rotatingZone;
            solidBodyMotionFunction  rotatingMotion;
            origin      {foam_vector(dom['origin'])};
            axis        {foam_vector(dom['axis'])};
            rpm         {rpm};
        }}
        """,
    )

    write(
        case / "constant" / "physicalProperties",
        f"""
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      physicalProperties;
        }}

        viscosityModel  constant;
        nu              [0 2 -1 0 0 0 0] {nu};
        """,
    )

    write(
        case / "constant" / "momentumTransport",
        """
        FoamFile
        {
            format      ascii;
            class       dictionary;
            object      momentumTransport;
        }

        simulationType  RAS;
        RAS
        {
            model           kEpsilon;
            turbulence      on;
            printCoeffs     on;
        }
        """,
    )

    write(
        case / "system" / "controlDict",
        f"""
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      controlDict;
        }}

        application     foamRun;
        solver          incompressibleFluid;

        startFrom       startTime;
        startTime       0;
        stopAt          endTime;
        endTime         {end_time};

        deltaT          1e-5;
        writeControl    adjustableRunTime;
        writeInterval   {vol_write};
        purgeWrite      {purge};

        writeFormat     binary;
        writePrecision  6;
        writeCompression off;
        timeFormat      general;
        timePrecision   6;
        runTimeModifiable true;
        adjustTimeStep  yes;
        maxCo           {max_co};

        functions
        {{
            #includeFunc Q
            #include "surfaces"
            #include "forces"
        }}
        """,
    )

    # Cut plane normal: prefer axis cross a stable vector
    a = np.array(dom["axis"], dtype=float)
    helper = np.array([0.0, 0.0, 1.0]) if abs(a[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    n1 = np.cross(a, helper)
    n1 /= np.linalg.norm(n1) + 1e-15
    n2 = np.cross(a, n1)

    iso_block = ""
    if q_iso > 0:
        iso_block = f"""
        isoQ
        {{
            type            isoSurface;
            isoField        Q;
            isoValue        {q_iso};
            interpolate     true;
        }}
        """

    write(
        case / "system" / "surfaces",
        f"""
        surfaces
        {{
            type            surfaces;
            libs            ("libsampling.so");
            writeControl    adjustableRunTime;
            writeInterval   {surf_write};
            surfaceFormat   vtk;
            writeFormat     binary;
            fields          (p U Q);
            interpolationScheme cellPoint;

            surfaces
            (
                cutA
                {{
                    type            cutPlane;
                    planeType       pointAndNormal;
                    point           {foam_vector(dom['origin'])};
                    normal          {foam_vector(n1)};
                    interpolate     true;
                }}

                cutB
                {{
                    type            cutPlane;
                    planeType       pointAndNormal;
                    point           {foam_vector(dom['origin'])};
                    normal          {foam_vector(n2)};
                    interpolate     true;
                }}

                rotor
                {{
                    type            patch;
                    patches         ("rotor.*");
                    interpolate     true;
                }}
                {iso_block}
            );
        }}
        """,
    )

    write(
        case / "system" / "forces",
        f"""
        forces
        {{
            type          forces;
            libs          ("libforces.so");
            writeControl  timeStep;
            timeInterval  1;
            log           yes;
            patches       ("rotor.*");
            rho           rhoInf;
            rhoInf        {rho_inf};
            CofR          {foam_vector(dom['origin'])};
            pitchAxis     {foam_vector(dom['axis'])};
        }}
        """,
    )

    # decomposePar: hierarchical factors
    # factor nprocs into (nx,ny,nz) roughly
    def factor3(n: int):
        best = (n, 1, 1)
        for a in range(1, n + 1):
            if n % a:
                continue
            for b in range(1, n // a + 1):
                if (n // a) % b:
                    continue
                c = n // (a * b)
                if a * b * c == n:
                    cand = tuple(sorted((a, b, c), reverse=True))
                    if max(cand) < max(best):
                        best = cand
        return best

    f3 = factor3(nprocs)
    write(
        case / "system" / "decomposeParDict",
        f"""
        FoamFile
        {{
            format      ascii;
            class       dictionary;
            object      decomposeParDict;
        }}

        numberOfSubdomains {nprocs};
        method          hierarchical;
        hierarchicalCoeffs
        {{
            n               ({f3[0]} {f3[1]} {f3[2]});
            order           xyz;
        }}
        """,
    )

    write(
        case / "system" / "fvSchemes",
        """
        FoamFile
        {
            format      ascii;
            class       dictionary;
            object      fvSchemes;
        }

        ddtSchemes
        {
            default         Euler;
        }

        gradSchemes
        {
            default         Gauss linear;
        }

        divSchemes
        {
            default         none;
            div(phi,U)      Gauss linearUpwind grad(U);
            div(phi,k)      Gauss upwind;
            div(phi,epsilon) Gauss upwind;
            div((nuEff*dev2(T(grad(U))))) Gauss linear;
        }

        laplacianSchemes
        {
            default         Gauss linear corrected;
        }

        interpolationSchemes
        {
            default         linear;
        }

        snGradSchemes
        {
            default         corrected;
        }

        wallDist
        {
            method          meshWave;
        }
        """,
    )

    write(
        case / "system" / "fvSolution",
        """
        FoamFile
        {
            format      ascii;
            class       dictionary;
            object      fvSolution;
        }

        solvers
        {
            p
            {
                solver          GAMG;
                tolerance       1e-7;
                relTol          0.01;
                smoother        GaussSeidel;
            }
            pFinal
            {
                $p;
                relTol          0;
            }
            "pcorr.*"
            {
                $p;
                tolerance       1e-4;
                relTol          0;
            }
            MeshPhi
            {
                solver          smoothSolver;
                smoother        symGaussSeidel;
                tolerance       1e-2;
                relTol          0;
            }
            "(U|k|epsilon)"
            {
                solver          smoothSolver;
                smoother        symGaussSeidel;
                tolerance       1e-6;
                relTol          0.1;
            }
            "(U|k|epsilon)Final"
            {
                $U;
                relTol          0;
            }
        }

        PIMPLE
        {
            nOuterCorrectors 2;
            nCorrectors      1;
            nNonOrthogonalCorrectors 1;
            correctPhi       yes;
            correctMeshPhi   yes;
        }

        relaxationFactors
        {
            equations
            {
                ".*"            1;
            }
        }
        """,
    )

    # Mesh / run shell scripts inside the case
    write(
        case / "Allmesh",
        f"""
        #!/bin/sh
        cd "${{0%/*}}" || exit 1
        . "$WM_PROJECT_DIR/bin/tools/RunFunctions"

        runApplication blockMesh
        runApplication surfaceFeatures
        runApplication decomposePar -force -noFields
        runParallel snappyHexMesh -overwrite
        runParallel createBaffles -overwrite
        runParallel splitBaffles -overwrite
        runParallel renumberMesh -noFields -overwrite
        # Sliding interface between rotatingZone baffles
        runParallel createNonConformalCouples -overwrite nonCouple1 nonCouple2
        """,
    )
    (case / "Allmesh").chmod(0o755)

    write(
        case / "Allrun",
        f"""
        #!/bin/sh
        cd "${{0%/*}}" || exit 1
        . "$WM_PROJECT_DIR/bin/tools/RunFunctions"

        if [ ! -d processor0/constant/polyMesh ]; then
            ./Allmesh
        fi
        runApplication -a decomposePar -fields -copyZero
        runParallel $(getApplication)
        runApplication reconstructPar -latestTime || true
        """,
    )
    (case / "Allrun").chmod(0o755)

    write(
        case / "Allclean",
        """
        #!/bin/sh
        cd "${0%/*}" || exit 1
        . "$WM_PROJECT_DIR/bin/tools/CleanFunctions"
        cleanCase
        rm -rf constant/geometry/*.eMesh constant/extendedFeatureEdgeMesh postProcessing movies
        """,
    )
    (case / "Allclean").chmod(0o755)

    # Persist domain summary for movie / efficiency scripts
    import json

    meta = {
        "domain": dom,
        "rpm": rpm,
        "axis": axis,
        "u_inf": u_inf,
        "end_time": end_time,
        "period": period,
        "n_revolutions": n_rev,
        "surface_write_interval": surf_write,
        "volume_write_interval": vol_write,
        "movie_frames": n_frames,
        "movie_duration_sec": movie_dur,
        "movie_fps": movie_fps,
        "nprocs": nprocs,
        "mesh_preset": os.environ.get("MESH_PRESET", "demo"),
        "watertight": report,
        "stators": stator_names,
    }
    (case / "pipeline_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"Case written: {case}")
    print(f"endTime={end_time:.6g}s ({n_rev} rev @ {rpm} rpm)")
    print(f"surface samples ≈ {n_frames} every {surf_write:.6g}s → ~{movie_dur}s movie @ {movie_fps} fps")


if __name__ == "__main__":
    main()

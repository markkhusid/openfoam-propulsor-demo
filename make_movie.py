#!/usr/bin/env pvpython
"""
Build engineering demo frames from propeller surface VTK samples.

OpenFOAM layout produced by this case:
  postProcessing/surfaces/<time>/{zNormal,yNormal,propeller,isoQ}.vtk

Run in the OpenFOAM+ParaView container:
  pvpython make_movie.py
"""
from __future__ import print_function
import glob
import os
import sys

from paraview.simple import (
    ColorBy,
    GetActiveViewOrCreate,
    GetColorTransferFunction,
    GetAnimationScene,
    GetTimeKeeper,
    Show,
    LegacyVTKReader,
    WriteAnimation,
)

CASE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(CASE, "movies")
FRAMES_DIR = os.path.join(OUT_DIR, "frames")
os.makedirs(FRAMES_DIR, exist_ok=True)

SURF_ROOTS = [
    os.path.join(CASE, "postProcessing", "surfaces"),
    os.path.join(CASE, "processor0", "postProcessing", "surfaces"),
]


def list_times(root):
    if not os.path.isdir(root):
        return []
    times = []
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        try:
            times.append((float(name), name))
        except ValueError:
            continue
    times.sort(key=lambda x: x[0])
    return times


def series_for(root, surface_name):
    files = []
    for _, tname in list_times(root):
        for ext in (".vtk", ".vtp"):
            f = os.path.join(root, tname, surface_name + ext)
            if os.path.isfile(f):
                files.append(f)
                break
    return files


def main():
    root = None
    for r in SURF_ROOTS:
        if list_times(r):
            root = r
            break
    if root is None:
        print("ERROR: no surface times under postProcessing/surfaces", file=sys.stderr)
        sys.exit(1)

    z_files = series_for(root, "zNormal")
    p_files = series_for(root, "propeller")
    y_files = series_for(root, "yNormal")
    print("Surface root:", root)
    print("zNormal:", len(z_files), "propeller:", len(p_files), "yNormal:", len(y_files))
    if not z_files and not p_files:
        print("ERROR: no zNormal/propeller VTK series", file=sys.stderr)
        sys.exit(1)

    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = [1280, 720]
    view.Background = [0.07, 0.09, 0.12]
    view.OrientationAxesVisibility = 1

    # Primary: mid-plane velocity
    if z_files:
        z = LegacyVTKReader(FileNames=z_files)
        z.UpdatePipeline()
        d = Show(z, view)
        # Try U magnitude; fall back to p
        try:
            ColorBy(d, ("POINTS", "U", "Magnitude"))
            lut = GetColorTransferFunction("U")
            lut.ApplyPreset("Cool to Warm", True)
            d.SetScalarBarVisibility(view, True)
        except Exception:
            ColorBy(d, ("POINTS", "p"))
            d.SetScalarBarVisibility(view, True)
        d.RescaleTransferFunctionToDataRange(True, False)

    if p_files:
        prop = LegacyVTKReader(FileNames=p_files)
        prop.UpdatePipeline()
        d = Show(prop, view)
        try:
            ColorBy(d, ("POINTS", "p"))
        except Exception:
            pass
        d.RescaleTransferFunctionToDataRange(True, False)
        d.SetScalarBarVisibility(view, False)
        # solid-ish blades
        try:
            d.Opacity = 1.0
        except Exception:
            pass

    # Camera: axis of rotation is y; inflow -y
    view.CameraFocalPoint = [0.0, -0.30, 0.0]
    view.CameraPosition = [0.55, -0.15, 0.45]
    view.CameraViewUp = [0.0, 0.0, 1.0]
    try:
        view.ResetCamera(False)
    except Exception:
        view.ResetCamera()
    # Pull back for context after reset
    fp = list(view.CameraFocalPoint)
    pos = list(view.CameraPosition)
    # enlarge distance ~1.4x
    view.CameraPosition = [
        fp[0] + 1.4 * (pos[0] - fp[0]),
        fp[1] + 1.4 * (pos[1] - fp[1]),
        fp[2] + 1.4 * (pos[2] - fp[2]),
    ]

    scene = GetAnimationScene()
    tk = GetTimeKeeper()
    scene.UpdateAnimationUsingDataTimeSteps()
    scene.PlayMode = "Snap To TimeSteps"

    ntimes = len(tk.TimestepValues) if tk.TimestepValues else max(len(z_files), len(p_files))
    print("Animation timesteps:", ntimes)

    target_seconds = 10.0
    fps = max(8, min(24, int(round(ntimes / target_seconds)) if ntimes else 16))
    if fps < 1:
        fps = 12
    print("Nominal fps for ~10s:", fps)

    pattern = os.path.join(FRAMES_DIR, "frame_%04d.png")
    # Clear old frames
    for old in glob.glob(os.path.join(FRAMES_DIR, "frame_*.png")):
        os.remove(old)

    WriteAnimation(
        pattern,
        Magnification=1,
        FrameRate=fps,
        Compression=True,
    )

    meta = os.path.join(OUT_DIR, "movie_meta.txt")
    with open(meta, "w") as f:
        f.write("fps=%d\n" % fps)
        f.write("ntimes=%d\n" % ntimes)
        f.write("target_seconds=%s\n" % target_seconds)
        f.write("surface_root=%s\n" % root)
    print("Frames:", FRAMES_DIR)
    print("Meta:", meta)
    print("Done.")


if __name__ == "__main__":
    main()

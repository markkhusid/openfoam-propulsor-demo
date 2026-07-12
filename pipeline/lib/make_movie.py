#!/usr/bin/env pvpython
"""Render PNG frames from OpenFOAM surface VTK samples (legacy or XML)."""
from __future__ import print_function
import glob
import json
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
    XMLPolyDataReader,
    WriteAnimation,
)

CASE = os.environ.get("CASE_DIR", os.getcwd())
OUT_DIR = os.path.join(CASE, "movies")
FRAMES = os.path.join(OUT_DIR, "frames")
os.makedirs(FRAMES, exist_ok=True)

meta = {}
meta_path = os.path.join(CASE, "pipeline_meta.json")
if os.path.isfile(meta_path):
    with open(meta_path) as f:
        meta = json.load(f)

width = int(os.environ.get("MOVIE_WIDTH", meta.get("movie_width", 1280)))
height = int(os.environ.get("MOVIE_HEIGHT", meta.get("movie_height", 720)))
fps = int(float(os.environ.get("MOVIE_FPS", meta.get("movie_fps", 16))))
field = os.environ.get("MOVIE_FIELD", "U")


def list_times(root):
    if not os.path.isdir(root):
        return []
    out = []
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if not os.path.isdir(p):
            continue
        try:
            out.append((float(name), name))
        except ValueError:
            continue
    out.sort(key=lambda x: x[0])
    return out


def series(root, surface_name):
    files = []
    for _, tname in list_times(root):
        for ext in (".vtk", ".vtp"):
            f = os.path.join(root, tname, surface_name + ext)
            if os.path.isfile(f):
                files.append(f)
                break
    return files


def load_reader(files):
    if not files:
        return None
    if files[0].endswith(".vtp"):
        return XMLPolyDataReader(FileName=files)
    return LegacyVTKReader(FileNames=files)


def main():
    roots = [
        os.path.join(CASE, "postProcessing", "surfaces"),
        os.path.join(CASE, "processor0", "postProcessing", "surfaces"),
    ]
    root = None
    for r in roots:
        if list_times(r):
            root = r
            break
    if root is None:
        print("ERROR: no postProcessing/surfaces samples found", file=sys.stderr)
        sys.exit(1)

    # Prefer cutA, then zNormal (legacy demo), then cutB
    for name in ("cutA", "zNormal", "cutB", "yNormal"):
        cut_files = series(root, name)
        if cut_files:
            cut_name = name
            break
    else:
        cut_files, cut_name = [], None

    rotor_files = series(root, "rotor") or series(root, "propeller")

    print("Surface root:", root)
    print("cut:", cut_name, len(cut_files), "rotor/prop:", len(rotor_files))
    if not cut_files and not rotor_files:
        print("ERROR: no usable surfaces", file=sys.stderr)
        sys.exit(1)

    view = GetActiveViewOrCreate("RenderView")
    view.ViewSize = [width, height]
    view.Background = [0.07, 0.09, 0.12]
    view.OrientationAxesVisibility = 1

    if cut_files:
        cut = load_reader(cut_files)
        cut.UpdatePipeline()
        d = Show(cut, view)
        try:
            if field == "U":
                ColorBy(d, ("POINTS", "U", "Magnitude"))
                GetColorTransferFunction("U").ApplyPreset("Cool to Warm", True)
            else:
                ColorBy(d, ("POINTS", "p"))
            d.SetScalarBarVisibility(view, True)
            d.RescaleTransferFunctionToDataRange(True, False)
        except Exception as e:
            print("Colouring warning:", e)

    if rotor_files:
        rot = load_reader(rotor_files)
        rot.UpdatePipeline()
        d = Show(rot, view)
        try:
            ColorBy(d, ("POINTS", "p"))
            d.RescaleTransferFunctionToDataRange(True, False)
            d.SetScalarBarVisibility(view, False)
        except Exception:
            pass

    try:
        view.ResetCamera(False)
    except Exception:
        view.ResetCamera()
    fp = list(view.CameraFocalPoint)
    pos = list(view.CameraPosition)
    view.CameraPosition = [
        fp[0] + 1.35 * (pos[0] - fp[0]),
        fp[1] + 1.35 * (pos[1] - fp[1]),
        fp[2] + 1.35 * (pos[2] - fp[2]),
    ]

    scene = GetAnimationScene()
    tk = GetTimeKeeper()
    scene.UpdateAnimationUsingDataTimeSteps()
    scene.PlayMode = "Snap To TimeSteps"
    ntimes = len(tk.TimestepValues) if tk.TimestepValues else max(len(cut_files), len(rotor_files))
    print("timesteps:", ntimes, "fps:", fps)

    for old in glob.glob(os.path.join(FRAMES, "frame_*.png")):
        os.remove(old)

    pattern = os.path.join(FRAMES, "frame.png")
    WriteAnimation(pattern, Magnification=1, FrameRate=fps, Compression=True)

    # Normalize names written by various ParaView versions
    import re
    from pathlib import Path

    d = Path(FRAMES)
    for f in list(d.glob("frame*.png")):
        m = re.search(r"(\d+)\.png$", f.name)
        if not m:
            continue
        dest = d / ("frame_%04d.png" % int(m.group(1)))
        if f.resolve() != dest.resolve():
            if dest.exists():
                dest.unlink()
            f.rename(dest)

    with open(os.path.join(OUT_DIR, "movie_meta.txt"), "w") as f:
        f.write("fps=%d\n" % fps)
        f.write("ntimes=%d\n" % ntimes)
        f.write("width=%d\n" % width)
        f.write("height=%d\n" % height)
    print("Frames in", FRAMES)


if __name__ == "__main__":
    main()

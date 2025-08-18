#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
What this does (minimal pipeline for your “Method B” up to model build):
  • Reads scan *dates* from a simple text file (one date like 20250502T082851 per line).
  • For each matching scan folder under --root:
      <Datetime>__<uid>__<Species>__DISC3D
      ├─ <uid>__edof\*.png
      └─ <Datetime>__<uid>__<Species>__CamPos.txt
    - Adds photos as Single cameras
    - Sets Precalibrated f = 10276.64 px (only f to be optimized later)
    - Imports reference from CamPos.txt (Local coords; CRS optional)
    - Aligns photos (highest; generic+reference preselection; key/tie 250k)
    - Optimizes cameras with fit_f=True only (once)
    - Builds model from depth maps (Ultra, Mild, Arbitrary, High faces)
    - Saves project as a single-file .psz under scan\models\
    - Also exports calibrated cameras XML next to it (optional but small)

*WINDOWS*
Metashape 2.2.1 (Windows) — short, single-file batch for DISC3D

Run from Metashape on Windows (note the `--` separator):

  "C:\Program Files\Agisoft\Metashape Pro\metashape.exe" -r M:\disc3d_simple_win.py -- ^
      --root "M:\TEST" ^
      --list "M:\TEST\ScanFolderFiles.txt" ^
      --mm-prj "M:\mm.prj" ^
      --f-px 10276.64 \

If you don’t have an mm.prj (Local Coordinates in millimeters), omit --mm-prj —
the script will import reference without an explicit CRS (OK for this stage).

*LINUX*
Metashape 2.2.1 (linux) — short, single-file batch for DISC3D
DISC3D → Metashape batch pipeline (Method B, headless, Linux)
Run with Metashape itself (NOT system Python), for example:

  /opt/metashape/metashape.sh -r /path/to/disc3d_batch_metashape.py -- \
      --root "/mnt/data/scans" \
      --list /mnt/data/SampleBatch.txt \
      --mm-prj /mnt/data/mm.prj \
      --f-px 10276.64 \
      --gpu 0
      #--skip-existing (in development)

Notes
-----
* Uses only Python stdlib + Metashape API.
* Optional stdlib-only path shim via CUSTOM_PYTHONPATH environment variable.
* Robust Metashape API guards for versions 1.5–2.x where names/enum locations differ.
* Mirrors “Method B — no preexisting Calibrated_Cameras.xml”.
* Saves .psx after each major step; logs to stdout and per-scan log file.

Author
------
Joachim Snellings - Data-Architect | DevOp - ELIO (Museum für Naturkunde) Berlin

"""

import sys, os, re, argparse
from pathlib import Path
from datetime import datetime

# Must run under Metashape Python:
import Metashape


# ---------- tiny helpers (kept short & 2.2.1-friendly) ----------

def ms(val_chain):
    """Return the first Metashape attribute that exists from a list of dotted names."""
    for path in val_chain:
        obj = Metashape
        ok = True
        for part in path.split("."):
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                ok = False
                break
        if ok:
            return obj
    return None


def read_dates(txt_path: Path):
    """
    Read lines like 20250502T082851 from ScanFolderFiles.txt.
    Ignores blanks and lines starting with '#'.
    """
    dates = []
    pat = re.compile(r"^\s*(\d{8}T\d{6})\s*$")
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        m = pat.match(line)
        if m:
            dates.append(m.group(1))
    return dates


def find_scans(root: Path, dates):
    """
    Find scan folders like:
      <Datetime>__<uid>__<Species>__DISC3D
    whose Datetime matches one of the dates.
    """
    found = []
    for d in root.rglob("*__DISC3D"):
        if not d.is_dir():
            continue
        name = d.name
        if "__" not in name:
            continue
        if any(name.startswith(dt + "__") for dt in dates):
            found.append(d)
    return sorted(found)


def get_uid_and_dataset(scan_dir: Path):
    """Extract uid from '<uid>__edof' and dataset_id from folder name (strip '__DISC3D')."""
    dataset_id = scan_dir.name.replace("__DISC3D", "")
    uid = None
    for ed in scan_dir.glob("*__edof"):
        if ed.is_dir():
            m = re.match(r"^(.+?)__edof$", ed.name)
            if m:
                uid = m.group(1)
                break
    return uid, dataset_id


def load_crs(mm_prj: Path):
    """Load WKT from mm.prj if present, else return None (we proceed without CRS)."""
    if mm_prj and mm_prj.exists():
        wkt = mm_prj.read_text(encoding="utf-8").strip()
        if wkt:
            return Metashape.CoordinateSystem(wkt)
    return None


# ---------- core per-scan pipeline (short & focused) ----------

def process_scan(scan_dir: Path, f_px: float, crs):
    """
    Minimal “Method B” up to model build, then save .psz.
    Returns (status, message).
    """
    uid, dataset_id = get_uid_and_dataset(scan_dir)
    if not uid:
        return ("fail", "No '<uid>__edof' folder found")

    edof = scan_dir / f"{uid}__edof"
    imgs = sorted(edof.glob("*.png"))
    if not imgs:
        return ("fail", f"No PNGs in {edof}")

    campos_list = list(scan_dir.glob("*__CamPos.txt"))
    if len(campos_list) != 1:
        return ("fail", "Missing or multiple CamPos.txt")
    campos = campos_list[0]

    models = scan_dir / "models"
    models.mkdir(exist_ok=True)
    psz = models / f"{dataset_id}.psz"
    cams_xml = models / f"{dataset_id}_Calibrated_Cameras_{uid}_{dataset_id.split('__')[0]}.xml"

    # Start project
    doc = Metashape.Document()
    chunk = doc.addChunk()
    chunk.label = "DISC3D"
    doc.save(str(psz))  # archive format because extension is .psz

    # Add photos (as Single cameras)
    chunk.addPhotos([str(p) for p in imgs])
    doc.save()

    # ---- Precalibrated intrinsics: seed f [px], keep others 0, allow optimizing f only
    if not chunk.sensors:
        return ("fail", "No sensor after adding photos")
    sensor = chunk.sensors[0]
    cal = Metashape.Calibration()
    # carry over image size if known (helps UI show correct resolution)
    try:
        if getattr(sensor, "width", None):
            cal.width = sensor.width
        if getattr(sensor, "height", None):
            cal.height = sensor.height
    except Exception:
        pass

    cal.f  = float(f_px)
    cal.cx = cal.cy = 0
    cal.k1 = cal.k2 = cal.k3 = cal.k4 = 0
    cal.p1 = cal.p2 = 0
    cal.b1 = cal.b2 = 0

    # Make it "Precalibrated" in UI and seed the working calibration
    sensor.user_calib = cal
    sensor.calibration = cal
    sensor.fixed_calibration = False  # important: we still want to optimize f later
    doc.save()

    # Import reference (Label X Y Z; space-delimited; cameras; no rotations/accuracies)
    if crs:
        chunk.crs = crs
        if hasattr(chunk, "camera_crs"):
            chunk.camera_crs = crs

    chunk.importReference(
        path=str(campos),
        format=Metashape.ReferenceFormatCSV,
        columns="nxyz",          # Label, X, Y, Z
        delimiter=" ",
        items=Metashape.ReferenceItemsCameras,  # be explicit
        crs=crs if crs else None,
        skip_rows=1,             # set to 1 if your file has a header row
        group_delimiters=False
    )
    doc.save()

  
    # Match & align (highest; generic+reference; 250k/250k; keep keypoints; guided off; no adaptive)
    # For 2.2.1, passing accuracy enum works; to keep it short we rely on the built-in names.
    try:
        chunk.matchPhotos(
            accuracy=Metashape.HighestAccuracy,
            generic_preselection=True,
            reference_preselection=True,
            reference_preselection_mode=Metashape.ReferencePreselectionSource,
            keypoint_limit=250000,
            tiepoint_limit=250000,
            keep_keypoints=False,
            guided_matching=False,
            filter_stationary_points=True
        )
    except Exception:
        # fallback with downscale=0 (highest) if enum name differs
        chunk.matchPhotos(
            downscale=0,
            generic_preselection=True,
            reference_preselection=True,
            reference_preselection_mode=Metashape.ReferencePreselectionSource,
            keypoint_limit=250000,
            tiepoint_limit=250000,
            keep_keypoints=False,
            guided_matching=False,
            filter_stationary_points=True
        )
    # --- after alignment ---
    try:
        chunk.alignCameras(adaptive_fitting=False)
    except TypeError:
        chunk.alignCameras()
    doc.save()

    # -------- QC snapshot: duplicate the aligned chunk (sparse-only) --------
    # Keeps a frozen copy for inspection; we continue processing on the original 'chunk'.
    qc_chunk = None
    try:
        qc_chunk = chunk.copy()          # Metashape 2.x
    except Exception:
        try:
            qc_chunk = chunk.duplicate() # fallback for odd bindings
        except Exception:
            qc_chunk = None

    if qc_chunk:
        try:
            qc_chunk.label = f"{chunk.label}__QC_ALIGNED"   # e.g., "DISC3D__QC_ALIGNED"
        except Exception:
            pass
        # Disable it so later scripts that iterate over chunks won't process it by accident.
        try:
            qc_chunk.enabled = False
        except Exception:
            pass
        doc.save()
    else:
        print("[WARN] QC chunk could not be duplicated; continuing.")

    # -----------------------------------------------------------------------
    # Continue with your pipeline on the ORIGINAL 'chunk' (optimize, depth, mesh)

    # Optimize cameras — ONLY f  (matches Tools > Optimize Cameras… with only “Fit f” checked)
    try:
        chunk.optimizeCameras(
            fit_f=True, fit_cx=False, fit_cy=False,
            fit_b1=False, fit_b2=False,
            fit_k1=False, fit_k2=False, fit_k3=False, fit_k4=False,
            fit_p1=False, fit_p2=False, fit_p3=False, fit_p4=False,
            adaptive_fitting=False
        )
    except TypeError:
        # Older kw set
        chunk.optimizeCameras(
            fit_f=True, fit_cx=False, fit_cy=False,
            fit_b1=False, fit_b2=False,
            fit_k1=False, fit_k2=False, fit_k3=False, fit_k4=False,
            fit_p1=False, fit_p2=False
        )
    doc.save()

    # Build depth maps (Ultra = downscale=1) + Mild filtering
    try:
        chunk.buildDepthMaps(downscale=1, filter_mode=Metashape.MildFiltering)
    except TypeError:
        # compatibility with older kw names
        try:
            chunk.buildDepthMaps(quality=Metashape.UltraQuality, filter=Metashape.MildFiltering)
        except Exception:
            chunk.buildDepthMaps()
    doc.save()

    # Build mesh from depth maps
    try:
        # 2.2.x signature (no reuse_depth/keep_depth here)
        chunk.buildModel(
            source_data=Metashape.DepthMapsData,
            surface_type=Metashape.Arbitrary,
            interpolation=Metashape.EnabledInterpolation,
            face_count=Metashape.HighFaceCount,
            vertex_colors=True
        )
    except TypeError:
        # legacy signature
        try:
            chunk.buildModel(
                source=Metashape.DepthMapsData,
                surface=Metashape.Arbitrary,
                interpolation=Metashape.EnabledInterpolation,
                face_count=Metashape.HighFaceCount,
                vertex_colors=True
            )
        except Exception:
            # minimal last-resort call
            chunk.buildModel()
    doc.save()

    # Export calibrated cameras (XML) next to the .psz  — Metashape 2.2.x signature
    try:
        chunk.exportCameras(
            path=str(cams_xml),
            format=Metashape.CamerasFormatXML,
            crs=crs if crs else None,      # <- 2.2.x uses 'crs'
            save_points=True,              # <- 2.2.x uses 'save_*'
            save_markers=False,
            use_labels=False
        )
    except TypeError:
        # Legacy fallback (<=1.6 style) in case this script is ever run on very old installs
        chunk.exportCameras(
            path=str(cams_xml),
            format=Metashape.CamerasFormatXML,
            projection=crs if crs else None,
            export_points=True,
            export_markers=False,
            use_labels=False
        )
    # Final save (archive .psz)
    doc.save()
    return ("ok", f"Saved {psz}  cams_xml={cams_xml}")


# ---------- CLI / main ----------

def main(argv=None):
    ap = argparse.ArgumentParser(description="Short DISC3D batch (Windows Metashape 2.2.1)")
    ap.add_argument("--root", required=True, help="Root folder containing scan directories")
    ap.add_argument("--list", required=True, help="ScanFolderFiles.txt with one Datetime per line (e.g., 20250502T082851)")
    ap.add_argument("--mm-prj", default=None, help="Optional mm.prj (WKT) for Local Coordinates (mm)")
    ap.add_argument("--f-px", type=float, default=10276.64, help="Precalibrated f in pixels (default: 10276.64)")
    ap.add_argument("--gpu", type=int, default=None, help="GPU index to use (Linux/Windows headless)")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"[ERR] Root not found: {root}", file=sys.stderr)
        sys.exit(2)
        
    # after args parsed
    if args.gpu is not None:
        try:
            Metashape.app.gpu_mask = 1 << int(args.gpu)  # pin to GPU N
            Metashape.app.cpu_enable = True
        except Exception:
            pass

    lst = Path(args.list)
    if not lst.exists():
        print(f"[ERR] List file not found: {lst}", file=sys.stderr)
        sys.exit(2)

    dates = read_dates(lst)
    if not dates:
        print(f"[ERR] No valid dates in {lst}", file=sys.stderr)
        sys.exit(2)

    crs = load_crs(Path(args.mm_prj)) if args.mm_prj else None
    scans = find_scans(root, dates)

    if not scans:
        print("[WARN] No matching scan folders found.")
        sys.exit(1)

    ok = 0
    for s in scans:
        status, msg = process_scan(s, args.f_px, crs)
        ds = s.name.replace("__DISC3D", "")
        if status == "ok":
            ok += 1
            print(f"OK   {ds}  {msg}")
        else:
            print(f"FAIL {ds}  reason={msg}", file=sys.stderr)

    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    # When run by Metashape, it passes its own args first.
    main(sys.argv[1:])





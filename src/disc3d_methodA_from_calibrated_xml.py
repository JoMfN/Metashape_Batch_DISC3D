# -*- coding: utf-8 -*-
"""
disc3d_methodA_from_calibrated_xml.py
Metashape 2.2.1 — DISC3D batch (Windows/Linux), Method A (preexisting Calibrated_Cameras XML)

Purpose:
  • Start from exported calibrated cameras (XML) produced earlier.
  • Import cameras (intrinsics + reference) and keep intrinsics LOCKED (cx, cy, f, k*, p* not fitted).
  • Align with reference preselection (Source) and build model from depth maps.

Inputs per scan folder:
  <Datetime>__<uid>__<Species>__DISC3D/
    ├─ <uid>__edof/*.png
    ├─ <Datetime>__<uid>__<Species>__CamPos.txt      (not used; XML has the reference)
    └─ models/<dataset>_Calibrated_Cameras_*.xml     (existing calibrated cameras)

Run (Linux):
  /opt/metashape/metashape.sh -r /path/disc3d_methodA_from_calibrated_xml.py -- \
    --root "/data/TEST" \
    --list "/data/TEST/ScanFolderFiles.txt" \
    --mm-prj "/data/mm.prj" \
    --gpu 0
"""

import sys, re, argparse
from pathlib import Path
import Metashape

def read_dates(p: Path):
    dates, pat = [], re.compile(r"^\s*(\d{8}T\d{6})\s*$")
    for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"): continue
        m = pat.match(ln);  if m: dates.append(m.group(1))
    return dates

def find_scans(root: Path, dates):
    hits = []
    for d in root.rglob("*__DISC3D"):
        if d.is_dir() and any(d.name.startswith(dt+"__") for dt in dates):
            hits.append(d)
    return sorted(hits)

def get_uid_dataset(scan_dir: Path):
    ds = scan_dir.name.replace("__DISC3D", "")
    uid = None
    for ed in scan_dir.glob("*__edof"):
        m = re.match(r"^(.+?)__edof$", ed.name)
        if m: uid = m.group(1); break
    return uid, ds

def load_crs(mm_prj: Path|None):
    if mm_prj and mm_prj.exists():
        wkt = mm_prj.read_text(encoding="utf-8", errors="ignore").strip()
        if wkt: return Metashape.CoordinateSystem(wkt)
    return None

def enable_gpu_index(idx: int|None):
    if idx is None: return
    try:
        Metashape.app.gpu_mask = 1 << int(idx)
        Metashape.app.cpu_enable = True
        print(f"[GPU] using index {idx} (mask=0x{Metashape.app.gpu_mask:x})")
    except Exception as e:
        print(f"[GPU] warn: {e}")

def thin_project(chunk, clear_depth=True, clear_matches=True):
    if clear_depth:
        try: chunk.clearDepthMaps()
        except AttributeError:
            try: chunk.depth_maps = None
            except Exception: pass
    if clear_matches and hasattr(chunk, "removeMatches"):
        try: chunk.removeMatches()
        except Exception: pass

def process_scan(scan_dir: Path, crs, gpu_index: int|None,
                 xml_glob: str, key_limit: int, tie_limit: int,
                 keep_keypoints: bool, keep_depth: bool, keep_matches: bool):
    uid, dataset_id = get_uid_dataset(scan_dir)
    if not uid: return ("fail", "No '<uid>__edof' folder found")
    edof = scan_dir / f"{uid}__edof"
    imgs = sorted(edof.glob("*.png"))
    if not imgs: return ("fail", f"No PNGs in {edof}")

    models = scan_dir / "models";  models.mkdir(exist_ok=True)
    psz = models / f"{dataset_id}.psz"

    # find calibrated cameras xml
    xml = None
    for cand in sorted(models.glob(xml_glob)):
        xml = cand; break
    if not xml:
        return ("fail", f"No calibrated cameras XML found in {models} matching '{xml_glob}'")

    doc = Metashape.Document()
    chunk = doc.addChunk(); chunk.label = "DISC3D"
    doc.save(str(psz))
    enable_gpu_index(gpu_index)

    # Add photos
    chunk.addPhotos([str(p) for p in imgs])
    doc.save()

    # Set CRS first (so imported cameras reference goes to Local mm)
    if crs:
        chunk.crs = crs
        if hasattr(chunk, "camera_crs"): chunk.camera_crs = crs

    # Import calibrated cameras (XML) — includes intrinsics + reference
    try:
        chunk.importCameras(str(xml), Metashape.CamerasFormatXML, crs if crs else None)
    except TypeError:
        try:
            chunk.importCameras(str(xml), Metashape.CamerasFormatXML)
        except Exception as e:
            return ("fail", f"importCameras failed: {e}")
    try: chunk.updateTransform()
    except Exception: pass

    # Lock intrinsics completely (Method A uses pre-calibrated cameras)
    for s in chunk.sensors:
        try:
            s.fixed_calibration = True
        except Exception:
            pass

    # Align with reference preselection (Source); keep intrinsics fixed
    try:
        chunk.matchPhotos(
            accuracy=Metashape.HighestAccuracy,
            generic_preselection=True,
            reference_preselection=True,
            reference_preselection_mode=Metashape.ReferencePreselectionSource,
            keypoint_limit=int(key_limit),
            tiepoint_limit=int(tie_limit),
            keep_keypoints=bool(keep_keypoints),
            guided_matching=False,
            filter_stationary_points=True
        )
    except Exception:
        chunk.matchPhotos(
            downscale=0,
            generic_preselection=True,
            reference_preselection=True,
            reference_preselection_mode=Metashape.ReferencePreselectionSource,
            keypoint_limit=int(key_limit),
            tiepoint_limit=int(tie_limit),
            keep_keypoints=bool(keep_keypoints),
            guided_matching=False,
            filter_stationary_points=True
        )
    try:
        chunk.alignCameras(adaptive_fitting=False)
    except TypeError:
        chunk.alignCameras()
    doc.save()

    # Optional bundle adjustment WITHOUT changing intrinsics (all fit_* False)
    try:
        chunk.optimizeCameras(
            fit_f=False, fit_cx=False, fit_cy=False,
            fit_b1=False, fit_b2=False,
            fit_k1=False, fit_k2=False, fit_k3=False, fit_k4=False,
            fit_p1=False, fit_p2=False,
            fit_corrections=False, adaptive_fitting=False, tiepoint_covariance=False
        )
    except TypeError:
        pass
    doc.save()

    # Build model from depth maps
    try:
        chunk.buildDepthMaps(quality=Metashape.UltraQuality, filter=Metashape.MildFiltering)
    except Exception:
        try: chunk.buildDepthMaps(downscale=1, filter_mode=Metashape.MildFiltering)
        except Exception: chunk.buildDepthMaps()
    doc.save()

    try:
        chunk.buildModel(source_data=Metashape.DepthMapsData,
                         surface_type=Metashape.Arbitrary,
                         interpolation=Metashape.EnabledInterpolation,
                         face_count=Metashape.HighFaceCount,
                         vertex_colors=True)
    except TypeError:
        try:
            chunk.buildModel(source=Metashape.DepthMapsData, surface=Metashape.Arbitrary,
                             interpolation=Metashape.EnabledInterpolation,
                             face_count=Metashape.HighFaceCount, vertex_colors=True)
        except Exception:
            chunk.buildModel()
    doc.save()

    # Trim project size before the final save (default ON)
    thin_project(chunk, clear_depth=not keep_depth, clear_matches=not keep_matches)
    doc.save()

    return ("ok", f"Saved {psz}  using XML={xml.name}")

def main(argv=None):
    ap = argparse.ArgumentParser(description="DISC3D batch — Method A (Metashape 2.2.1)")
    ap.add_argument("--root", required=True)
    ap.add_argument("--list", required=True)
    ap.add_argument("--mm-prj", default=None)
    ap.add_argument("--gpu", type=int, default=None)
    ap.add_argument("--xml-glob", default="*_Calibrated_Cameras_*.xml",
                    help="Pattern to locate calibrated cameras XML inside models/ (default: *_Calibrated_Cameras_*.xml)")
    ap.add_argument("--key-limit", type=int, default=250000)
    ap.add_argument("--tie-limit", type=int, default=250000)
    ap.add_argument("--keep-keypoints", action="store_true")
    ap.add_argument("--keep-depth", action="store_true")
    ap.add_argument("--keep-matches", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root); lst = Path(args.list)
    if not root.exists(): print(f"[ERR] Root not found: {root}", file=sys.stderr); sys.exit(2)
    if not lst.exists():  print(f"[ERR] List not found: {lst}", file=sys.stderr); sys.exit(2)

    dates = read_dates(lst)
    if not dates: print(f"[ERR] No valid dates in {lst}", file=sys.stderr); sys.exit(2)
    crs = load_crs(Path(args.mm_prj)) if args.mm_prj else None
    scans = find_scans(root, dates)
    if not scans: print("[WARN] No matching scan folders."); sys.exit(1)

    ok = 0
    for s in scans:
        status, msg = process_scan(
            s, crs, args.gpu, args.xml_glob,
            key_limit=args.key_limit, tie_limit=args.tie_limit,
            keep_keypoints=args.keep_keypoints,
            keep_depth=args.keep_depth, keep_matches=args.keep_matches
        )
        ds = s.name.replace("__DISC3D", "")
        if status == "ok": ok += 1; print(f"OK   {ds}  {msg}")
        else: print(f"FAIL {ds}  reason={msg}", file=sys.stderr)
    if ok == 0: sys.exit(1)

if __name__ == "__main__":
    main(sys.argv[1:])

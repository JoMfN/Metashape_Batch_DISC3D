# DISC3D Batch — Metashape 2.2.1

> **Purpose:** A reproducible, GPU-friendly batch pipeline to build `.psz` projects (and optionally textures/exports) for DISC3D insect scans. The pipeline aligns photos, optimizes only `f`, builds depth maps & mesh, saves the project, and (optionally) imports precomputed 2D masks to remove the mounting pin before any heavy computation.

---

## Features

* **Headless batch** on Windows & Linux (Metashape 2.2.1), GPU pinning for multi-worker boxes.
* **Precalibrated intrinsics** (optimize **`f` only**) for consistency with manual workflow.
* **Camera reference import** from `CamPos.txt` (Local Coordinates in **mm**) with or without CRS.
* **Masks-first (optional)**: import per-photo PNG masks (255=masked, 0=keep) **before** matching to exclude the pin.
* **QC snapshot**: duplicate an aligned sparse-only chunk for inspection while the main chunk continues to mesh.
* **Robust API calls** for 2.2.x (with legacy fallbacks for older bindings).

---

## Requirements

* **Agisoft Metashape Pro 2.2.1** (GUI and/or headless `metashape.sh`/`metashape.exe`).
* **NVIDIA GPU** (recommended), recent driver; CPU-only also works (slower).
* **Python 3.9+** (for the mask generator CLI).
* Python packages (mask generator): `Pillow`, `numpy`.
* Optional CRS: `config/mm.prj` (WKT) describing *Local Coordinates (mm)*.

> The batch scripts themselves run inside Metashape’s Python, while the **mask generator** runs with system Python.

---

## Directory layout (suggested)

```
disc3d-batch/
├─ src/
│  ├─ MetashapeBatch.py              # Stage A: build .psz (align → optimize f → depth → mesh)
│  ├─ TextureExport.py               # Stage B: texture + exports (optional)
│  ├─ make_disc3d_masks.py           # CLI: generate per-photo PNG masks
│  ├─ config/
│  │  └─ mm.prj                         # Local Coordinates (mm) (optional)
│  ├─ templates/
│  │  └─ masks/                         # one PNG per photo filename (255=mask)
│  └─ utils/                         # (optional helpers)
├─ queues/                           # text lists for worker scripts (Linux)
├─ logs/
└─ docs/
   ├─ mask_protocol.md               # how to draw/QA masks
   └─ runbook.md                     # operational runbook (Stage A/B; QC)
```

---

## Installation

### A) Get the code

```bash
# clone this repository
git clone https://github.com/JoMfN/Metashape_Batch_DISC3D.git
cd Metashape_Batch_DISC3D
```

### B) Mask generator (system Python)

```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install --upgrade pip
pip install pillow numpy
```

or conda... 


### C) Metashape 2.2.1

* Install Metashape Pro 2.2.1 and activate your license.
* **Windows:** `"C:\\Program Files\\Agisoft\\Metashape Pro\\metashape.exe"`
* **Linux:** `/opt/metashape-pro/metashape.sh`

> No extra Python packages are required inside Metashape for Stage A/B.

---

## Quick Start

### 1) Prepare masks (optional but recommended)

Generate a **template mask pack** once from a representative `__edof` folder. Masks are 8‑bit PNG (255=masked pin, 0=keep), saved by **exact photo filename**.

```bash
# Windows PowerShell example
python src/make_disc3d_masks.py `
  --src "M:\DATA\20250502T145837__067870__Carabus_violaceus_meyeri__DISC3D\067870__edof" `
  --out "templates\masks" `
  --auto-center `
  --shaft-width 14 --head-radius 22
```

### 2) Stage A — Build `.psz` (headless)

**Windows**

```bat
"C:\Program Files\Agisoft\Metashape Pro\metashape.exe" -r src\MetashapeBatch.py -- ^
  --root "M:\DATA" ^
  --list "M:\DATA\ScanFolderFiles.txt" ^
  --mm-prj "config\mm.prj" ^
  --f-px 10276.64 ^
  --mask-dir "templates\masks" ^
  --skip-rows 1 ^
  --gpu 0
```

**Linux**

```bash
/opt/metashape/metashape.sh -r src/MetashapeBatch.py -- \
  --root /mnt/data/DATA \
  --list /mnt/data/DATA/ScanFolderFiles.txt \
  --mm-prj config/mm.prj \
  --f-px 10276.64 \
  --mask-dir templates/masks \
  --skip-rows 1 \
  --gpu 0
```

> `--gpu N` pins the process to GPU *N* so you can run **two parallel workers** on a dual-GPU box.

### 3) Stage B — Texture & exports (optional)

Run later (batch or manual) on the `.psz` that passed QC. Example knobs: `buildUV`, `buildTexture`, `exportModel(OBJ/PLY/GLB)`.

---

## Workflow details

### Mask-first (preprocessing)

* Create one PNG per photo filename, stored in `templates/masks/`.
* White (255) = **mask out** (pin, background to ignore). Black (0) = keep specimen.
* Import right after `addPhotos()` so masks apply to **matching**, **depth**, and **mesh**.

**Import snippet (2.2.1)**

```python
# After chunk.addPhotos([...])
from pathlib import Path
mask_dir = Path(args.mask_dir) if args.mask_dir else None
if mask_dir:
    try:
        chunk.importMasks(
            path=str(mask_dir / "{filename}.png"),
            cameras=chunk.cameras,
            operation=Metashape.MaskOperationReplacement
        )
    except Exception:
        for cam in chunk.cameras:
            fp = mask_dir / Path(cam.photo.path).name
            if fp.exists():
                cam.importMask(path=str(fp), operation=Metashape.MaskOperationReplacement)
    doc.save()
```

### Intrinsics & reference

* **Precalibrated** intrinsics; seed `f = 10276.64 px`; other terms 0; **do not** fix calibration → later optimize **`f` only**.
* Import camera reference from `CamPos.txt`:

```python
chunk.importReference(
    path=str(campos),
    format=Metashape.ReferenceFormatCSV,
    columns="nxyz",           # Label, X, Y, Z
    delimiter=" ",
    items=Metashape.ReferenceItemsCameras,
    crs=crs if crs else None,
    skip_rows=int(args.skip_rows),
    group_delimiters=False
)
```

### Match → Align → Optimize (Fit f)

```python
chunk.matchPhotos(
    accuracy=Metashape.HighestAccuracy,
    generic_preselection=True,
    reference_preselection=True,
    keypoint_limit=250000,
    tiepoint_limit=250000,
    keep_keypoints=False,
    guided_matching=False,
    filter_stationary_points=True
)
chunk.alignCameras(adaptive_fitting=False)
doc.save()

# QC snapshot chunk (sparse-only)
qc_chunk = None
try: qc_chunk = chunk.copy()
except Exception:
    try: qc_chunk = chunk.duplicate()
    except Exception: qc_chunk = None
if qc_chunk:
    qc_chunk.label = f"{chunk.label}__QC_ALIGNED"
    qc_chunk.enabled = False
    doc.save()

# Optimize Cameras… (only Fit f)
chunk.optimizeCameras(
    fit_f=True, fit_cx=False, fit_cy=False,
    fit_k1=False, fit_k2=False, fit_k3=False, fit_k4=False,
    fit_p1=False, fit_p2=False, fit_p3=False, fit_p4=False,
    fit_b1=False, fit_b2=False,
    adaptive_fitting=False
)
doc.save()
```

### Depth maps & mesh (2.2.1 argument names)

```python
# Depth maps (Ultra = downscale=1), Mild filtering
try:
    chunk.buildDepthMaps(downscale=1, filter_mode=Metashape.MildFiltering)
except TypeError:
    chunk.buildDepthMaps(quality=Metashape.UltraQuality, filter=Metashape.MildFiltering)
doc.save()

# Mesh from depth maps (2.2.x: source_data, surface_type)
try:
    chunk.buildModel(
        source_data=Metashape.DepthMapsData,
        surface_type=Metashape.Arbitrary,
        interpolation=Metashape.EnabledInterpolation,
        face_count=Metashape.HighFaceCount,
        vertex_colors=True
    )
except TypeError:
    chunk.buildModel(
        source=Metashape.DepthMapsData,
        surface=Metashape.Arbitrary,
        interpolation=Metashape.EnabledInterpolation,
        face_count=Metashape.HighFaceCount,
        vertex_colors=True
    )
doc.save()
```

### Export calibrated cameras (XML)

```python
# 2.2.x uses crs= and save_points/save_markers
try:
    chunk.exportCameras(
        path=str(cams_xml),
        format=Metashape.CamerasFormatXML,
        crs=crs if crs else None,
        save_points=True,
        save_markers=False,
        use_labels=False
    )
except TypeError:
    chunk.exportCameras(
        path=str(cams_xml),
        format=Metashape.CamerasFormatXML,
        projection=crs if crs else None,
        export_points=True,
        export_markers=False,
        use_labels=False
    )
```

---

## Linux multi-GPU batching

Run one worker per GPU by pinning `--gpu N`:

```bash
# worker for GPU 0
/opt/metashape/metashape.sh -r src/MetashapeBatch.py -- \
  --root /mnt/data/DATA \
  --list /mnt/data/DATA/ScanFolderFiles.txt \
  --mm-prj config/mm.prj \
  --mask-dir templates/masks \
  --skip-rows 1 \
  --gpu 0 &

# worker for GPU 1
/opt/metashape/metashape.sh -r src/MetashapeBatch.py -- \
  --root /mnt/data/DATA \
  --list /mnt/data/DATA/ScanFolderFiles.txt \
  --mm-prj config/mm.prj \
  --mask-dir templates/masks \
  --skip-rows 1 \
  --gpu 1 &

wait
```

---

## Troubleshooting

**Argument name errors (2.2.x):**

* `buildModel(source=…)` → use `source_data=`
* `buildModel(surface=…)` → use `surface_type=`
* `buildDepthMaps(filter=…)` → use `filter_mode=` (or fallback)
* `exportCameras(projection=…)` → use `crs=`
* `exportCameras(export_points=…)` → use `save_points=`

**`CamPos.txt` has a header row?** set `--skip-rows 1`.

**Missing masks warning:** batch logs will list filenames without masks; these photos will process unmasked.

**Units:** CRS in **mm** does not change reconstruction quality; it sets export units and scales distances/thresholds consistently. To export in meters, either rescale on export or use a meter-based CRS.

---

## FAQ

**Do we have to use masks?** No, but masks remove the pin before matching → fewer spurious tie points and more consistent meshes. Keep a manual cleanup step as fallback.

**Why optimize only `f`?** Matches the existing manual protocol; keeps intrinsics stable while letting the effective focal length adapt slightly to the dataset.

**Where is the QC step?** Right after alignment we duplicate a sparse-only chunk (`__QC_ALIGNED`) and disable it, so you can inspect camera positions/tie points without touching the main processing chunk.

---

## License

MIT

---

## Changelog (example)

* **v0.1.0** — Initial public version; 2.2.1 argument fixes; mask-first import; QC snapshot; Linux GPU pinning.

---

## Acknowledgements

This workflow was developed to support scalable, consistent digitization for museum-grade DISC3D acquisitions, with alignment settings and calibration choices tuned to mirror prior manual practice.
The effective handling and capture of the focus stacked images were done by Emily B.

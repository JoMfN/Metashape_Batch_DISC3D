# Filename: archive_disc3d_labels.py
# Required Packages: pip install PyPDF2 jsons
# for Windows usage: replace path with 'D:\\YOURFILEPATH' at the respective Names for the paths. For linux use paths '/SOME/PATH" notatiion. Pathlib is there to make all of this compatible with the code below
# LABEL_JSON_BASE is the path to the Transcription .json files of the labels from the GV-analyser output (see GV-analyser) change the line 117 for the prefered name of the metadata csv file that will be created after the script successfully finalized the archiving -- "metadata_extracted_SomeID.csv"
# In the script folder you could after filling in the paths just prompt: `python archive_disc3d_labels.py`and the operation should be executed without errors

import os
import re
import json
import shutil
from pathlib import Path
from PyPDF2 import PdfReader
from datetime import datetime
import csv

LABEL_JSON_BASE = Path(r"A:\\ExtractedLabelsAndTranscriptionPath")
# LABEL_JSON_BASE = Path(r"/mnt/data/ExtractedLabelsAndTranscriptionPath") # LINUX

def normalize_species(s):
    return s.strip().replace(" ", "_").replace("(", "").replace(")", "")

def resolve_label_suffix(name: str) -> str:
    """Determines standardized label suffix from stem or filename."""
    name = name.lower()
    if "recto" in name or "label_r" in name:
        return "label_recto"
    elif "verso" in name or "label_v" in name:
        return "label_verso"
    elif re.search(r"\(\d+\)", name):
        return "label_2"
    return "label"

def reformat_name(original_name):
    pattern = r"u_(?P<uid>[a-z0-9]+)__\s*(?P<species>[^_]+)__"
    match = re.search(pattern, original_name)
    if match:
        return match.group("uid"), normalize_species(match.group("species"))
    return None, None

def extract_metadata_from_pdf(pdf_path):
    metadata = {}
    try:
        reader = PdfReader(pdf_path)
        text = "\n".join([p.extract_text() for p in reader.pages if p.extract_text()])

        date_match = re.search(r"Date:\s+\w+\s+(\w+)\s+(\d+)\s+(\d+)", text)
        time_match = re.search(r"Start Time:\s+(\d{2}):(\d{2}):(\d{2})", text)
        if date_match and time_match:
            month_str, day, year = date_match.groups()
            hour, minute, second = time_match.groups()
            month_map = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                         'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                         'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'}
            month = month_map.get(month_str[:3], '01')
            metadata["datetime"] = f"{year}{month}{day.zfill(2)}T{hour}{minute}{second}"

        patterns = {
            "camera_name": r"Name:\s*(\S+)",
            "pixel_pitch_um": r"Pixel Pitch \[um\]:\s*([\d.]+)",
            "size_px_height": r"Height \[px\]:\s*(\d+)",
            "size_px_width": r"Width \[px\]:\s*(\d+)",
            "lens": r"Lens:\s*(.+)",
            "f_number": r"F-Number:\s*([\d.]+)",
            "depth_of_field_mm": r"Depth of Field \[mm\]:\s*([\d.]+)",
            "magnification": r"Magnification:\s*([\d.]+)",
            "working_distance_mm": r"Working Distance \[mm\]:\s*([\d.]+)",
            "camera_constant_mm": r"Camera Constant \[mm\]:\s*([\d.]+)",
            "camera_constant_per_f_px": r"Camera Constant/f \[px\]:\s*([\d.]+)",
            "object_pixel_pitch_um": r"Object Pixel Pitch \[um\]:\s*([\d.]+)",
            "field_size_height_mm": r"Field Size.*?Height \[mm\]:\s*([\d.]+)",
            "field_size_width_mm": r"Field Size.*?Width \[mm\]:\s*([\d.]+)",
            "num_stack_images": r"Num Stack Images:\s*(\d+)",
            "range_mm": r"Range \[mm\]:\s*([\d.]+)",
            "step_size": r"Step Size:\s*(\w+)",
            "velocity_mm_s": r"Velocity \[mm/s\]:\s*([\d.]+)",
            "backlight_percent": r"Backlight \[%\]:\s*(\d+)",
            "exposure_time_ms": r"Exposure Time \[ms\]:\s*([\d.]+)",
            "frontlight_percent": r"Frontlight \[%\]:\s*(\d+)",
            "gain_db": r"Gain \[dB\]:\s*(\d+)",
            "image_enhancement": r"Image Enhancement:\s*(\w+)",
            "pose_programs": r"Pose Programms:\s*(.+?)\s*Δ =",
            "azimuth_release_time_s": r"Azimuth Release Time \[s\]:\s*([\d.]+)",
            "elevation_release_time_s": r"Elevation Release Time \[s\]:\s*([\d.]+)",
            "estimated_scan_time_min": r"Estimated Scan Time \[min\]:\s*([\d.]+)",
            "num_images": r"Num Images:\s*(\d+)",
            "required_memory_gb": r"Required Memory \[GB\]:\s*([\d.]+)",
            "end_time": r"End Time:\s*(\d{2}:\d{2}:\d{2})",
            "duration_min": r"Duration \[min\]:\s*([\d.]+)"
        }

        for key, pattern in patterns.items():
            match = re.search(pattern, text)
            if match:
                metadata[key] = match.group(1)

    except Exception as e:
        print(f"Failed reading {pdf_path}: {e}")
    return metadata

def extract_and_copy_label_jsons(uid, archive_root, dt, species):
    combined_text = ""
    for json_path in LABEL_JSON_BASE.glob(f"*{uid}*_label*.json"):
        suffix = resolve_label_suffix(json_path.stem)
        json_out = archive_root / f"{dt}__{uid}__{normalize_species(species)}__{suffix}__Text.json"
        txt_out = archive_root / f"{dt}__{uid}__{normalize_species(species)}__{suffix}__Text.txt"
        try:
            with open(json_path, encoding='utf-8') as jf:
                data = json.load(jf)
                combined_text += data.get("extracted_text", "") + "\n"
                with open(json_out, "w", encoding="utf-8") as jf_out:
                    json.dump(data, jf_out, indent=2, ensure_ascii=False)
                with open(txt_out, "w", encoding="utf-8") as tf_out:
                    tf_out.write(data.get("extracted_text", ""))
        except Exception as e:
            print(f"Error handling {json_path.name}: {e}")
    return combined_text.strip()

def archive_folders(root_path, archive_base, metadata_csv="metadata_extracted_SomeID.csv"):
    records = []
    for dirpath, _, filenames in os.walk(root_path):
        if "ScanInformation.pdf" not in filenames:
            continue
        parent = Path(dirpath)
        scan_pdf = parent / "ScanInformation.pdf"
        metadata = extract_metadata_from_pdf(scan_pdf)
        dt = metadata.get("datetime")
        uid, species = reformat_name(parent.name)
        if not all([dt, uid, species]):
            print(f"Skipping malformed: {parent.name}")
            continue
        archive_dir = Path(archive_base) / f"{dt}__{uid}__{species}__DISC3D"
        archive_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy(scan_pdf, archive_dir / f"{dt}__{uid}__{species}__ScanInformation.pdf")
        campos = parent / "CamPos.txt"
        if campos.exists():
            shutil.copy(campos, archive_dir / f"{dt}__{uid}__{species}__CamPos.txt")
        edof_src = parent / "edof"
        if edof_src.exists():
            shutil.copytree(edof_src, archive_dir / f"{uid}__edof", dirs_exist_ok=True)

        for label_dir in ["Labels", "Label"]:
            label_path = parent / label_dir
            if label_path.exists():
                for label_img in label_path.glob("*.jpg"):
                    suffix = resolve_label_suffix(label_img.stem)
                    new_img_name = f"{dt}__{uid}__{species}__{suffix}.jpg"
                    shutil.copy(label_img, archive_dir / new_img_name)

        label_text = extract_and_copy_label_jsons(uid, archive_dir, dt, species)
        records.append({"archive_dir": archive_dir.name, "folder": parent.name, "datetime": dt, "uid": uid, **metadata, "label_text": label_text})
        print(f"✓ Archived: {archive_dir.name}")

    output_csv = Path(archive_base) / metadata_csv
    with open(output_csv, "w", encoding="utf-8", newline="") as f:
        fieldnames = sorted({k for r in records for k in r})
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

# Example usage
archive_folders("K:\\OriginalScansFiles", "H:\\FinalizedArchivingPath")
# archive_folders("/mnt/data/OriginalScansFiles", "/mnt/data/FinalizedArchivingPath") # LINUX

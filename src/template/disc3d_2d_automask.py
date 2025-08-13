#!/usr/bin/env python3
# make_disc3d_masks.py
# Generates per-photo binary masks (255=masked pin, 0=keep) for DISC3D __edof images.
## Windows PowerShell
# python C:\repo\make_disc3d_masks.py `
#  --src "M:\DATA\20250502T145837__067870__Carabus_violaceus_meyeri__DISC3D\067870__edof" `
#  --out "M:\DISC3D\templates\masks" `
#  --auto-center `
#  --shaft-width 14 --head-radius 22
# ### 
# # Linux/macOS
# python make_disc3d_masks.py \
#   --src /data/SCANS_ROOT \
#   --out /repo/templates/masks \
#   --auto-center


import argparse, sys
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np

def list_images(root: Path):
    if root.is_file() and root.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return [root]
    if (root.name.endswith("__edof") and root.is_dir()):
        return sorted([p for p in root.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}])
    # walk for all __edof folders
    imgs = []
    for edof in root.rglob("*__edof"):
        imgs.extend(sorted([p for p in edof.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]))
    return imgs

def estimate_shaft_x(img_gray: np.ndarray, search_half_width_frac=0.15):
    """
    Find darkest narrow vertical structure near the center (the pin).
    Returns column index x (int).
    """
    H, W = img_gray.shape
    cx = W // 2
    hw = int(W * search_half_width_frac)
    lo, hi = max(0, cx - hw), min(W, cx + hw)

    # column means (pin is dark -> lower value)
    col_mean = img_gray[:, lo:hi].mean(axis=0)
    x_local = int(np.argmin(col_mean))
    return lo + x_local

def make_mask_for_image(
    w, h,
    shaft_x=None,
    shaft_width_px=14,
    y_top_frac=0.05,
    y_bot_frac=0.95,
    head_radius_px=20,
    head_y_frac=0.20
):
    """
    Returns a PIL L-mode image (8-bit) mask:
    255 = masked (pin), 0 = keep.
    """
    m = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(m)

    # Shaft rectangle
    x0 = int((shaft_x if shaft_x is not None else w/2) - shaft_width_px/2)
    x1 = x0 + shaft_width_px
    y0 = int(h * y_top_frac)
    y1 = int(h * y_bot_frac)
    dr.rectangle([x0, y0, x1, y1], fill=255)

    # Pin head (small disk near top)
    cy = int(h * head_y_frac)
    r  = int(head_radius_px)
    dr.ellipse([x0 + shaft_width_px//2 - r, cy - r,
                x0 + shaft_width_px//2 + r, cy + r], fill=255)
    return m

def main():
    ap = argparse.ArgumentParser(description="Generate DISC3D pin masks (255=mask, 0=keep)")
    ap.add_argument("--src", required=True, help="Path to a single __edof folder, an image file, or a root with many __edof folders")
    ap.add_argument("--out", required=True, help="Output folder that will contain one PNG per photo (flat, by filename)")
    ap.add_argument("--auto-center", action="store_true", help="Auto-detect shaft X near image center (recommended)")
    ap.add_argument("--shaft-width", type=int, default=14, help="Pin shaft width in pixels (default: 14)")
    ap.add_argument("--head-radius", type=int, default=20, help="Pin head radius in pixels (default: 20)")
    ap.add_argument("--y-top-frac", type=float, default=0.05, help="Top of shaft as fraction of height (default: 0.05)")
    ap.add_argument("--y-bot-frac", type=float, default=0.95, help="Bottom of shaft as fraction of height (default: 0.95)")
    ap.add_argument("--head-y-frac", type=float, default=0.20, help="Center Y of pin head as fraction of height (default: 0.20)")
    args = ap.parse_args()

    src = Path(args.src)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)

    images = list_images(src)
    if not images:
        print(f"[ERR] No images found under: {src}", file=sys.stderr); sys.exit(2)

    made = 0
    for img_path in images:
        try:
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                w, h = im.size

                shaft_x = None
                if args.auto_center:
                    g = np.asarray(im.convert("L"), dtype=np.float32)
                    shaft_x = estimate_shaft_x(g)

                m = make_mask_for_image(
                    w, h,
                    shaft_x=shaft_x,
                    shaft_width_px=args.shaft_width,
                    y_top_frac=args.y_top_frac,
                    y_bot_frac=args.y_bot_frac,
                    head_radius_px=args.head_radius,
                    head_y_frac=args.head_y_frac
                )

                # Save mask with EXACT photo filename (important!)
                dst = out / Path(img_path).name
                m.save(dst, format="PNG", optimize=True)
                made += 1
        except Exception as e:
            print(f"[WARN] failed on {img_path.name}: {e}", file=sys.stderr)

    print(f"[OK] Wrote {made} masks to {out}")

if __name__ == "__main__":
    main()

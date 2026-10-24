"""
Offline GT landmark/mask precompute for Kaleido training (run once).

Input: a CSV where every garment row already carries its own landmarks
and segmentation - no JSON files needed:
  path, b_box (or clean_bbox), category_id, landmarks, segmentation,
  img_width, img_height
For every row:
  1. Parse landmarks (flat [x1, y1, v1, ...]) and count visible points.
  2. Rasterize the segmentation polygons into a fabric mask.
  3. Crop the mask with the training crop box and save it as a small PNG.
Output: enriched CSV with landmarks_orig_json / crop_box_used / mask_file.
"""
import os
import sys
import ast
import json
import argparse
import pandas as pd
import numpy as np
from PIL import Image
from tqdm import tqdm
from pathlib import Path

# مسیرهای پروژه در Google Drive
SCRIPT_DIR = Path(__file__).resolve().parent
MODEL_ROOT = SCRIPT_DIR.parent
PROJECT_ROOT = MODEL_ROOT.parent

# اضافه کردن مسیرهای پروژه به Python
for folder in (PROJECT_ROOT, MODEL_ROOT):
    folder = str(folder)
    if folder not in sys.path:
        sys.path.insert(0, folder)

from model.vision.cropper import GarmentCropper
from model.kaleido.df2_landmark_schema import (
    parse_landmarks_to_array, rasterize_segmentations,
)


def _find_col(df, *names):
    """First existing column name from the alias list (or None)."""
    for n in names:
        if n in df.columns:
            return n
    return None


def _parse_cell(value):
    """Parse a CSV cell holding a Python/JSON list (or None)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (list, tuple)):
        return list(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        try:
            return json.loads(text)
        except ValueError:
            return None


def enrich_split(preprocessed_csv: str, output_csv: str, masks_dir: str,
                 padding_pct: float = 0.05, checkpoint_interval: int = 500):
    if not os.path.exists(preprocessed_csv):
        print(f"File not found: {preprocessed_csv}")
        return
    os.makedirs(masks_dir, exist_ok=True)
    df = pd.read_csv(preprocessed_csv).reset_index(drop=True)
    print(f"[Precompute] {len(df):,} rows from {preprocessed_csv}")

    # Resolve real column names (CSVs differ slightly).
    c_path = _find_col(df, "path", "image", "file")
    c_box = _find_col(df, "clean_bbox", "b_box", "bbox")
    c_lm = _find_col(df, "landmarks", "landmark")
    c_seg = _find_col(df, "segmentation", "segmentations", "segm")
    c_w = _find_col(df, "img_width", "width", "w")
    c_h = _find_col(df, "img_height", "height", "h")
    print(f"  columns: path={c_path} box={c_box} landmarks={c_lm} "
          f"segmentation={c_seg} size=({c_w},{c_h})")
    if c_box is None or c_w is None or c_h is None:
        print("Missing required columns (box / image size). Abort.")
        return

    # Resume: rows already in the output are skipped (same input order).
    start = 0
    existing = None
    if os.path.exists(output_csv):
        try:
            existing = pd.read_csv(output_csv)
            if "landmarks_orig_json" in existing.columns:
                start = min(len(existing), len(df))
                print(f"Resuming from row {start:,}.")
        except (OSError, ValueError):
            existing = None
            start = 0

    new_cols = {"landmarks_orig_json": [], "crop_box_used": [],
                "mask_file": [], "lm_source": [], "n_visible": []}

    rows = df.iloc[start:].iterrows()
    for idx, row in tqdm(rows, total=len(df) - start, desc="Extracting GT landmarks"):
        bbox = [float(v) for v in _parse_cell(row[c_box])[:4]]
        W = int(row[c_w] or 0)
        H = int(row[c_h] or 0)
        img_name = os.path.basename(str(row[c_path])) if c_path else f"row{idx}.jpg"

        lm_json, box_json, mask_rel, src, n_vis = "", "", "", "none", 0
        if W > 0 and H > 0:
            lm_arr = parse_landmarks_to_array(
                _parse_cell(row[c_lm])) if c_lm else None
            if lm_arr is not None and len(lm_arr) > 0:
                flat = np.asarray(lm_arr, dtype=np.float32).reshape(-1).tolist()
                lm_json = json.dumps([round(v, 1) for v in flat])
                n_vis = int((np.asarray(lm_arr)[:, 2] >= 1).sum())
                src = "csv"
            crop_box = GarmentCropper.padded_box(W, H, bbox, padding_pct)
            box_json = json.dumps(crop_box)
            m_full = rasterize_segmentations(
                _parse_cell(row[c_seg]), W, H) if c_seg else None
            if m_full is None:  # fallback: fill the box rectangle
                m_full = np.zeros((H, W), dtype=bool)
                x1, y1, x2, y2 = [int(max(0, v)) for v in bbox]
                m_full[y1:min(y2, H), x1:min(x2, W)] = True
            cx1, cy1, cx2, cy2 = crop_box
            stem = os.path.splitext(img_name)[0]
            fname = f"{stem}_r{idx}.png"
            Image.fromarray(m_full[cy1:cy2, cx1:cx2].astype(np.uint8) * 255).save(
                os.path.join(masks_dir, fname))
            mask_rel = os.path.join(masks_dir, fname)

        new_cols["landmarks_orig_json"].append(lm_json)
        new_cols["crop_box_used"].append(box_json)
        new_cols["mask_file"].append(mask_rel)
        new_cols["lm_source"].append(src)
        new_cols["n_visible"].append(n_vis)

        done = len(new_cols["lm_source"])
        if done % checkpoint_interval == 0:
            _flush(df.iloc[:start + done], existing, new_cols, output_csv)

    _flush(df, existing, new_cols, output_csv)
    n_ok = sum(1 for s in new_cols["lm_source"] if s == "csv")
    print(f"\nDone: {n_ok:,}/{len(df) - start:,} new rows got GT landmarks -> {output_csv}")


def _flush(df_part, existing, new_cols, output_csv):
    """Merge processed rows with the resumed checkpoint and save."""
    skip = len(existing) if existing is not None else 0
    out_new = df_part.iloc[skip:].copy()
    for k, v in new_cols.items():
        out_new[k] = v[:len(out_new)]
    out = pd.concat([existing, out_new], ignore_index=True) \
        if existing is not None else out_new
    os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
    out.to_csv(output_csv, index=False)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Precompute GT landmarks/masks for Kaleido")
    p.add_argument("--input_csv", default="preprocessed_data/preprocessed_train.csv")
    p.add_argument("--output_csv", default="preprocessed_data/enriched_train.csv")
    p.add_argument("--masks_dir", default="preprocessed_data/masks_train")
    p.add_argument("--padding", type=float, default=0.05)
    p.add_argument("--checkpoint_interval", type=int, default=500)
    a = p.parse_args()
    enrich_split(a.input_csv, a.output_csv, a.masks_dir,
                 a.padding, a.checkpoint_interval)

"""
Train.csv -> YOLO instance-segmentation dataset (trains yolo26n-seg).

Input:  a CSV row per garment: path, category_id (1..13), segmentation
        (list of polygons, flat or Nx2, in pixels), img_width, img_height.
Output: out/
          images/train/<img>, images/val/<img>   (symlinks to the originals)
          labels/train/<stem>.txt, labels/val/<stem>.txt
             one line per polygon:  cls x1 y1 x2 y2 ...   (cls 0-based, coords 0..1)
          data.yaml                              (13 DeepFashion2 names)

Then train with:
  yolo segment train model=yolo26n-seg.pt data=<out>/data.yaml epochs=80 imgsz=640
"""
import os
import sys
import ast
import json
import shutil
import argparse
import numpy as np
import pandas as pd
from tqdm import tqdm

from model.kaleido.garment_parse import DF2_CATEGORIES


def _find_col(df, *names):
    for n in names:
        if n in df.columns:
            return n
    return None


def _parse_cell(value):
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


def _polygons_to_lines(seg, W, H, cls):
    """Segmentation cell -> list of YOLO-seg label lines (or empty)."""
    lines = []
    polys = seg if isinstance(seg, list) else [seg]
    for poly in polys:
        try:
            pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
        except (ValueError, TypeError):
            continue
        if len(pts) < 3 or W <= 0 or H <= 0:
            continue
        pts[:, 0] = np.clip(pts[:, 0] / W, 0.0, 1.0)
        pts[:, 1] = np.clip(pts[:, 1] / H, 0.0, 1.0)
        coords = " ".join(f"{v:.5f}" for v in pts.reshape(-1))
        lines.append(f"{cls} {coords}")
    return lines


def convert(preprocessed_csv: str, out_dir: str, img_root: str = "",
            copy_images: bool = False, val_frac: float = 0.05,
            limit: int = 0, seed: int = 7):
    df = pd.read_csv(preprocessed_csv).reset_index(drop=True)
    if limit and limit < len(df):
        df = df.iloc[:limit]
    print(f"[YOLO-seg] {len(df):,} rows from {preprocessed_csv}")

    c_path = _find_col(df, "path", "image", "file")
    c_cat = _find_col(df, "category_id", "category", "label")
    c_seg = _find_col(df, "segmentation", "segmentations", "segm")
    c_w = _find_col(df, "img_width", "width", "w")
    c_h = _find_col(df, "img_height", "height", "h")
    print(f"  columns: path={c_path} category={c_cat} segmentation={c_seg} size=({c_w},{c_h})")
    if c_path is None or c_cat is None or c_seg is None or c_w is None or c_h is None:
        print("Missing required columns. Abort.")
        return

    # One label file per image (several garments can share an image).
    per_image = {}
    skip = {"no_seg": 0, "bad_cat": 0, "missing_img": 0}
    for _, row in tqdm(df.iterrows(), total=len(df), desc="Converting rows"):
        try:
            cid = int(row[c_cat])
        except (TypeError, ValueError):
            skip["bad_cat"] += 1
            continue
        if not 1 <= cid <= 13:
            skip["bad_cat"] += 1
            continue
        rel = str(row[c_path])
        src = os.path.join(img_root, rel) if img_root else rel
        if not os.path.exists(src):
            skip["missing_img"] += 1
            continue
        lines = _polygons_to_lines(_parse_cell(row[c_seg]),
                                   int(row[c_w] or 0), int(row[c_h] or 0), cid - 1)
        if not lines:
            skip["no_seg"] += 1
            continue
        per_image.setdefault(rel, {"src": src, "lines": []})["lines"].extend(lines)

    # Deterministic train/val split by image.
    rng = np.random.RandomState(seed)
    rels = sorted(per_image)
    rng.shuffle(rels)
    n_val = int(round(len(rels) * val_frac))
    val_set = set(rels[:n_val])

    for split in ("train", "val"):
        os.makedirs(os.path.join(out_dir, "images", split), exist_ok=True)
        os.makedirs(os.path.join(out_dir, "labels", split), exist_ok=True)
    for rel in tqdm(rels, desc="Writing dataset"):
        split = "val" if rel in val_set else "train"
        src = per_image[rel]["src"]
        dst = os.path.join(out_dir, "images", split, os.path.basename(rel))
        if not os.path.exists(dst):
            if copy_images:
                shutil.copy2(src, dst)
            else:
                try:
                    os.symlink(os.path.abspath(src), dst)
                except OSError:
                    shutil.copy2(src, dst)  # filesystems without symlinks
        stem = os.path.splitext(os.path.basename(rel))[0]
        with open(os.path.join(out_dir, "labels", split, f"{stem}.txt"), "w") as f:
            f.write("\n".join(per_image[rel]["lines"]) + "\n")

    with open(os.path.join(out_dir, "data.yaml"), "w", encoding="utf-8") as f:
        f.write(f"path: {os.path.abspath(out_dir)}\ntrain: images/train\nval: images/val\nnames:\n")
        for i, name in enumerate(DF2_CATEGORIES):
            f.write(f"  {i}: {name}\n")

    n_lab = sum(len(v["lines"]) for v in per_image.values())
    print(f"\nDone: {len(rels):,} images ({len(rels) - len(val_set):,} train / {len(val_set):,} val), "
          f"{n_lab:,} polygons -> {out_dir}")
    print(f"Skipped rows: {skip}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Train.csv -> YOLO-seg dataset")
    p.add_argument("--input_csv", default="preprocessed_data/preprocessed_train.csv")
    p.add_argument("--out_dir", default="preprocessed_data/yoloseg_df2")
    p.add_argument("--img-root", default="", help="Prefix for the CSV 'path' column (if relative).")
    p.add_argument("--copy", action="store_true", help="Copy images instead of symlinking.")
    p.add_argument("--val-frac", type=float, default=0.05)
    p.add_argument("--limit", type=int, default=0, help="Convert only the first N rows (smoke test).")
    a = p.parse_args()
    convert(a.input_csv, a.out_dir, a.img_root, a.copy, a.val_frac, a.limit)

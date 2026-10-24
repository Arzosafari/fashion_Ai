"""
DeepFashion2 landmark schema + annotation helpers.

1. Landmark counts of the 13 categories (294 total) + the semantic landmark groups
   (upper_boundary / side / hem), read from landmark_groups.json (taken from Figure 2
   of the official repo).
2. Parser for the official DeepFashion2 JSON files (phase-3 finetune only).
3. Segmentation rasterization into a binary fabric mask.
4. Audit + visualization tools for one-time verification.

FIXES vs the previous version
  * DEFAULT_LANDMARK_COUNTS had wrong values for 5 categories (the sum was 294 by coincidence).
  * REGION_FRACTIONS assumed landmarks are numbered from collar to hem. They are NOT
    (e.g. long sleeve top: hem = 19-21, while 24-33 are the right sleeve and shoulder).
    Regions now come from explicit per-category index tables.
"""
import os
import json
import glob
from collections import Counter, defaultdict
from typing import Dict, List, Tuple, Optional, Any, Sequence

import numpy as np
from PIL import Image, ImageDraw


from model.kaleido.garment_parse import DF2_CATEGORIES, DF2_LANDMARK_COUNTS
from model.kaleido import kpg_geometry as _kg
# 1. Categories and landmark counts
DF2_CATEGORY_NAMES = {i + 1: n for i, n in enumerate(DF2_CATEGORIES)}
DEFAULT_LANDMARK_COUNTS = {i + 1: n for i, n in enumerate(DF2_LANDMARK_COUNTS)}
assert sum(DEFAULT_LANDMARK_COUNTS.values()) == 294

KPG_GROUP_OF_CATEGORY = {
    1: "top", 2: "top", 3: "outerwear", 4: "outerwear", 5: "top", 6: "top",
    7: "bottom", 8: "bottom", 9: "bottom",
    10: "dress", 11: "dress", 12: "dress", 13: "dress",
}


# 2. Semantic landmark groups (explicit index tables, 0-based)
def get_region_groups(category_id: int) -> Dict[str, List[List[int]]]:
    """{"upper_boundary": [[ids]], "side": [[left cuff ids], [right cuff ids]], "hem": [[ids]]}.

    A region can have several candidate groups (left / right sleeve); the planner
    uses the one with most visible points. Regions a category does not have are absent.
    """
    spec = _kg.LANDMARK_GROUPS.get(DF2_CATEGORY_NAMES[int(category_id)], {})
    out: Dict[str, List[List[int]]] = {}
    for region, ids in spec.items():
        out[region] = ids if (ids and isinstance(ids[0], list)) else [ids]
    return out


def get_region_indices(category_id: int) -> Dict[str, List[int]]:
    """Flat version of get_region_groups (all candidate groups merged)."""
    return {r: sorted({i for g in groups for i in g})
            for r, groups in get_region_groups(category_id).items()}


def filter_visible(landmarks: Optional[np.ndarray],
                   idx_list: List[int],
                   min_vis: int = 1) -> np.ndarray:
    """Valid (x, y) points of one region. v=2 visible, v=1 occluded, v=0 skip."""
    if landmarks is None or len(idx_list) == 0:
        return np.zeros((0, 2), dtype=np.float32)
    lm = np.asarray(landmarks, dtype=np.float32).reshape(-1, 3)
    pts = [[lm[i, 0], lm[i, 1]] for i in idx_list
           if 0 <= i < len(lm) and lm[i, 2] >= min_vis]
    if not pts:
        return np.zeros((0, 2), dtype=np.float32)
    return np.asarray(pts, dtype=np.float32)


# 3. Official DeepFashion2 JSON helpers
def load_df2_items(json_path: str) -> List[dict]:
    """Read garment items from one annotation file.

    Supports the official numbered format:
        {"source": ..., "pair_id": ..., "item1": {...}, "item2": {...}}
    plus the generic {"annotations": [...]} layout.
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if isinstance(data, dict):
        if isinstance(data.get("annotations"), list):
            return [d for d in data["annotations"] if isinstance(d, dict)]
        # official files use keys "item1", "item2", ...; also accept plain "1", "2"
        numbered = [data[k] for k in data
                    if isinstance(data[k], dict)
                    and (str(k).isdigit() or str(k).startswith("item"))]
        if numbered:
            return numbered
    return []


def item_bbox_xyxy(item: dict) -> Optional[List[float]]:
    raw = item.get("bounding_box", item.get("bbox"))
    if raw is None:
        return None
    x1, y1, x2, y2 = [float(v) for v in raw[:4]]
    if x2 <= x1 or y2 <= y1:  # xywh layout -> convert to xyxy
        x2, y2 = x1 + max(x2, 1.0), y1 + max(y2, 1.0)
    return [x1, y1, x2, y2]


def item_category(item: dict) -> Optional[int]:
    cid = item.get("category_id", item.get("category"))
    try:
        return int(cid) if cid is not None else None
    except (TypeError, ValueError):
        return None


def parse_landmarks_to_array(raw: Any) -> Optional[np.ndarray]:
    """Convert JSON landmarks to an [K, 3] array of (x, y, v).

    Accepts a flat list, a list of triplets, or a numbered dict.
    """
    if raw is None:
        return None
    try:
        if isinstance(raw, dict):
            keys = sorted([k for k in raw if str(k).isdigit()], key=int)
            trips = [raw[k] for k in keys] if keys else list(raw.values())
            return np.asarray(trips, dtype=np.float32).reshape(-1, 3)
        arr = np.asarray(raw, dtype=np.float32)
        if arr.ndim == 1 and arr.size % 3 == 0:
            return arr.reshape(-1, 3)
        if arr.ndim == 2 and arr.shape[1] == 3:
            return arr
    except (ValueError, TypeError):
        return None
    return None


def item_landmarks(item: dict) -> Optional[np.ndarray]:
    raw = item.get("landmarks", item.get("keypoints"))
    arr = parse_landmarks_to_array(raw)
    return arr if arr is not None and len(arr) > 0 else None


def item_segmentation(item: dict) -> Optional[list]:
    return item.get("segmentation", item.get("masks"))


def _as_polygons(seg: Any) -> list:
    """Segmentation cell -> list of polygons (each flat or Nx2).

    A flat list of NUMBERS is one polygon, not a list of polygons: without this
    check the loop below would walk over single floats and silently lose the shape.
    """
    if seg is None:
        return []
    if isinstance(seg, list) and seg and all(isinstance(v, (int, float)) for v in seg):
        return [seg]
    return seg if isinstance(seg, list) else [seg]


def rasterize_segmentations(seg: Any, img_w: int, img_h: int) -> Optional[np.ndarray]:
    """Rasterize segmentation polygons into a binary (H, W) fabric mask."""
    if seg is None:
        return None
    try:
        canvas = Image.new("L", (img_w, img_h), 0)
        draw = ImageDraw.Draw(canvas)
        drew = False
        for poly in _as_polygons(seg):
            pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
            if len(pts) >= 3:
                draw.polygon([tuple(p) for p in pts.tolist()], fill=255)
                drew = True
        return (np.asarray(canvas) > 127) if drew else None
    except (ValueError, TypeError):
        return None


def check_landmark_array(category_id: Any, keypoints: Any) -> tuple:
    """(ok, reason): is this [K, 3] array usable for the category?

    Length mismatches only WARN (the count table itself is still being audited
    on real data); downstream code guards every index, so a wrong length can
    never crash planning, it just falls back to lower tiers.
    """
    try:
        cid = int(category_id)
    except (TypeError, ValueError):
        return False, f"bad category_id: {category_id!r}"
    if cid not in DEFAULT_LANDMARK_COUNTS:
        return False, f"category_id {cid} outside 1..13"
    if keypoints is None:
        return False, "no keypoints (planner falls back)"
    try:
        n = int(np.asarray(keypoints).reshape(-1, 3).shape[0])
    except (ValueError, TypeError):
        return False, "keypoints are not [K, 3]"
    exp = DEFAULT_LANDMARK_COUNTS[cid]
    if n != exp:
        return True, (f"WARNING: cat-{cid} has {n} points, table expects {exp} "
                      f"(audit the counts; planning continues with guards)")
    return True, ""


# 4. One-time verification tools
def audit_counts_from_json(json_dir: str, limit: int = 3000) -> Dict[int, int]:
    """Print the most common landmark count per category from real JSONs
    and compare with DEFAULT_LANDMARK_COUNTS."""
    files = sorted(glob.glob(os.path.join(json_dir, "*.json")))[:limit]
    votes: Dict[int, Counter] = defaultdict(Counter)
    for jp in files:
        try:
            items = load_df2_items(jp)
        except (OSError, ValueError):
            continue
        for it in items:
            cid = item_category(it)
            lm = item_landmarks(it)
            if cid is not None and lm is not None:
                votes[int(cid)][int(len(lm))] += 1
    result = {}
    print(f"{'cid':>4} | {'name':<22} | {'found':>7} | {'expected':>8}")
    for cid in range(1, 14):
        if votes[cid]:
            best = votes[cid].most_common(1)[0][0]
            result[cid] = best
            flag = "" if best == DEFAULT_LANDMARK_COUNTS[cid] else "  <-- MISMATCH"
            print(f"{cid:>4} | {DF2_CATEGORY_NAMES[cid]:<22} | {best:>7} | {DEFAULT_LANDMARK_COUNTS[cid]:>8}{flag}")
        else:
            result[cid] = DEFAULT_LANDMARK_COUNTS[cid]
            print(f"{cid:>4} | {DF2_CATEGORY_NAMES[cid]:<22} | {'(none)':>7} | {DEFAULT_LANDMARK_COUNTS[cid]:>8}")
    print(f"\nTotal: {sum(result.values())} (paper says 294)")
    return result


def audit_counts_from_csv(csv_path: str, limit: int = 0) -> Dict[int, int]:
    """Same audit as above, but from a CSV (landmarks + category_id columns).

    Use this when the official JSONs are gone and only the CSV survived.
    """
    import ast
    import pandas as pd
    df = pd.read_csv(csv_path, sep=None, engine="python")
    if limit and limit < len(df):
        df = df.iloc[:limit]
    c_cat = next((c for c in ("category_id", "category", "label") if c in df.columns), None)
    c_lm = next((c for c in ("landmarks", "landmark") if c in df.columns), None)
    votes: Dict[int, Counter] = defaultdict(Counter)
    for _, row in df.iterrows():
        try:
            cid = int(row[c_cat])
            raw = row[c_lm]
            lm = ast.literal_eval(raw) if isinstance(raw, str) else raw
            n = int(np.asarray(lm, dtype=np.float32).reshape(-1, 3).shape[0])
            votes[cid][n] += 1
        except (TypeError, ValueError, SyntaxError):
            continue
    result = {}
    print(f"{'cid':>4} | {'name':<22} | {'found':>7} | {'expected':>8}")
    for cid in range(1, 14):
        if votes[cid]:
            best = votes[cid].most_common(1)[0][0]
            result[cid] = best
            flag = "" if best == DEFAULT_LANDMARK_COUNTS[cid] else "  <-- MISMATCH"
            print(f"{cid:>4} | {DF2_CATEGORY_NAMES[cid]:<22} | {best:>7} | {DEFAULT_LANDMARK_COUNTS[cid]:>8}{flag}")
        else:
            result[cid] = DEFAULT_LANDMARK_COUNTS[cid]
            print(f"{cid:>4} | {DF2_CATEGORY_NAMES[cid]:<22} | {'(none)':>7} | {DEFAULT_LANDMARK_COUNTS[cid]:>8}")
    print(f"\nTotal: {sum(result.values())} (paper says 294)")
    return result


def validate_groups() -> Dict[str, Any]:
    """Static check of the loaded index tables (run once, e.g. in tests).

    Verifies every group index is inside its category range and REPORTS index
    overlaps between regions (e.g. shorts side/hem share points). Overlaps are
    warnings, not errors: one landmark can legitimately anchor two regions, but
    two patches built from the same points must be inspected, not assumed fine.
    """
    report: Dict[str, Any] = {"errors": [], "overlaps": {}, "checked": 0}
    for cid in range(1, 14):
        name = DF2_CATEGORY_NAMES[cid]
        spec = _kg.LANDMARK_GROUPS.get(name, {})
        flat: Dict[str, set] = {}
        for region, ids in spec.items():
            cands = ids if (ids and isinstance(ids[0], list)) else [ids]
            pts = {i for g in cands for i in g}
            flat[region] = pts
            report["checked"] += 1
            bad = [i for i in pts if not 0 <= i < DEFAULT_LANDMARK_COUNTS[cid]]
            if bad:
                report["errors"].append(f"cat-{cid} {name} region '{region}': {bad} outside "
                                        f"0..{DEFAULT_LANDMARK_COUNTS[cid] - 1}")
        regions = sorted(flat)
        for a_i in range(len(regions)):
            for b_i in range(a_i + 1, len(regions)):
                a, b = regions[a_i], regions[b_i]
                shared = sorted(flat[a] & flat[b])
                if shared:
                    report["overlaps"].setdefault(name, []).append(
                        f"{a} & {b} share (0-based) {shared}")
    return report


def visualize_landmarks(image: Image.Image, landmarks: np.ndarray,
                        save_path: Optional[str] = None, title: str = ""):
    """Overlay numbered landmarks on an image to verify the grouping."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    lm = np.asarray(landmarks, dtype=np.float32).reshape(-1, 3)
    colors = {0: "gray", 1: "orange", 2: "lime"}
    fig, ax = plt.subplots(figsize=(6, 8))
    ax.imshow(image)
    for i, (x, y, v) in enumerate(lm):
        ax.scatter([x], [y], c=colors.get(int(v), "red"), s=28, zorder=3)
        ax.text(x + 3, y - 3, str(i + 1), color="yellow", fontsize=8,  # 1-based = same numbers as the paper figure
                bbox=dict(facecolor="black", alpha=0.55, pad=1))
    ax.set_title(title or f"{len(lm)} landmarks (green=visible, orange=occluded)")
    ax.axis("off")
    fig.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=120)
        print(f"Saved: {save_path}")
    plt.close(fig)

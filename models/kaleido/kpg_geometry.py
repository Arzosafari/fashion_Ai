# kpg_geometry.py
"""
Torch-free geometry of Semantic-KPG: decides WHICH 9 patches are cut from a garment image.

Patch slots (fixed order, also used as 'patch role' ids by the transformer):
    0 global | 1 upper_boundary(neckline/waistband) | 2 torso(thigh) | 3 side(sleeve/leg) | 4 hem | 5-8 fabric texture

Region source for upper_boundary / side / hem, in order of preference (tier):
    "table"      keypoints picked by LANDMARK_GROUPS (per-category index table)
    "spatial"    index-free: visible keypoints grouped by their position inside the garment
    "proportion" fixed proportions of the GARMENT box (not of the whole image)
    "none"       slot is invalid (e.g. sleeve slot of a vest / skirt)
Texture windows come from the fabric mask (windows fully inside the fabric). Without a mask, a mask is
approximated by the convex hull of the visible keypoints ("hull" tier); without keypoints, from proportions.

Slot 1 anchors the TOP of the garment: the neckline on tops/dresses/outwear, the waistband on
bottoms. It is called "upper_boundary" (not "neck") because one name must fit all families.
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from model.kaleido.garment_parse import GarmentParse


ROLE_NAMES = ["global", "upper_boundary", "torso", "side", "hem", "tex0", "tex1", "tex2", "tex3"]
NUM_PATCHES = len(ROLE_NAMES)
FILL_RGB = (124, 116, 104)  # ImageNet mean -> becomes ~0 after normalization

# {"long sleeve top": {"upper_boundary": [0-based ids], "side": [[left cuff ids], [right cuff ids]], ...}, ...}
# (stored 0-based here; the json file itself uses the 1-based numbers of the paper figure)
# Loaded from landmark_groups.json (read from Figure 2 of the official DeepFashion2 repo).
# "side" may be a list of candidate groups (left/right): the one with most visible points is used.
LANDMARK_GROUPS: Dict[str, Dict[str, List[int]]] = {}

# legacy group names still accepted when reading a json file
_GROUP_ALIASES = {"neck": "upper_boundary"}


def _to_zero_based(v):
    return [_to_zero_based(x) for x in v] if (v and isinstance(v[0], list)) else [int(i) - 1 for i in v]


def load_landmark_groups(path: str) -> None:
    """The json uses the numbers printed in the DeepFashion2 figure (1-based); arrays are 0-based."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    LANDMARK_GROUPS.clear()
    for cat, groups in data.items():
        if cat.startswith("_"):
            continue
        LANDMARK_GROUPS[cat.lower()] = {_GROUP_ALIASES.get(r, r): _to_zero_based(v)
                                        for r, v in groups.items()}


_DEFAULT_GROUPS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "landmark_groups.json")
if os.path.exists(_DEFAULT_GROUPS):
    load_landmark_groups(_DEFAULT_GROUPS)

# fallback proportions relative to the garment box (x1, y1, x2, y2 in [0,1])
_PROP_UPPER = {"upper_boundary": (0.2, 0.0, 0.8, 0.35), "torso": (0.2, 0.25, 0.8, 0.75),
               "side": (0.0, 0.2, 0.35, 0.7), "hem": (0.15, 0.75, 0.85, 1.0)}
_PROP_LOWER = {"upper_boundary": (0.2, 0.0, 0.8, 0.25), "torso": (0.2, 0.2, 0.8, 0.6),
               "side": (0.0, 0.5, 0.45, 0.95), "hem": (0.1, 0.85, 0.9, 1.0)}
_TEX_CENTERS = [(0.5, 0.5), (0.38, 0.38), (0.62, 0.62), (0.5, 0.68)]


def slot_config(category: str) -> Tuple[str, bool]:
    """-> (family, has_side_slot). Accepts the 13 DeepFashion2 names and the legacy 4 families."""
    c = category.lower().replace("_", " ")
    if "dress" in c:
        fam = "dress"
    elif "outwear" in c or c == "outerwear":
        fam = "outerwear"
    elif any(k in c for k in ("shorts", "trousers", "skirt", "bottom", "pants")):
        fam = "bottom"
    else:
        fam = "top"
    if fam == "bottom":
        has_side = "skirt" not in c
    elif c in ("top", "outerwear", "dress"):
        has_side = True
    else:
        has_side = "sleeve" in c
    return fam, has_side


class PatchPlanner:
    KP_EXPAND = 0.4       # grow the box around keypoints (they lie on the edge, not around it)
    KP_MIN_FRAC = 0.20    # min patch side as a fraction of the garment size
    KP_MAX_FRAC = 0.60    # max patch side as a fraction of the garment size
    MIN_KP = 2

    def __init__(self, mask_background: bool = True, texture_coverage: float = 0.98):
        self.mask_background = mask_background
        self.texture_coverage = texture_coverage

    # public
    def plan(self, image: Image.Image, parse: Optional[GarmentParse] = None, category: str = "top"):
        """
        Returns:
            patches: list of 9 PIL square images (None where invalid)
            coords:  np.float32 [9, 5]  normalized [x1, y1, x2, y2, area] w.r.t. the input image.
                     The box is the FINAL square patch (it may stick out of the image where the
                     patch was mean-padded, so values can leave [0, 1]); it always matches the
                     pixels the visual backbone receives.
            valid:   np.bool_   [9]
            info:    dict role -> tier (for debugging)

        `image` and `parse` must live in the same pixel frame (the crop); the planner never
        rescales the crop, it only cuts squares out of it.
        """
        img = image.convert("RGB")
        W, H = img.size
        category = parse.category if parse is not None else category
        _, has_side = slot_config(category)

        mask = self._get_mask(parse, W, H)
        kp = self._get_keypoints(parse, W, H)
        mask_tier = "mask"
        if mask is None and kp is not None:
            mask = self._hull_mask(kp, W, H)  # approximate fabric region from the landmarks
            mask_tier = "hull"
            real_mask = False
        else:
            real_mask = mask is not None
        G = self._garment_box(mask, kp, parse, W, H)
        if real_mask and self.mask_background:  # never cut the background with an approximate hull
            img = self._suppress_background(img, mask)

        boxes: List[Optional[Tuple[float, float, float, float]]] = [(0.0, 0.0, float(W), float(H))]
        info = {"global": "full"}

        for role in ("upper_boundary", "torso", "side", "hem"):
            if role == "side" and not has_side:
                boxes.append(None); info[role] = "none"; continue
            box, tier = None, "proportion"
            if role != "torso":
                box, tier = self._from_keypoints(role, category, kp, G)
            if box is None:
                box, tier = self._from_proportions(role, category, G), "proportion"
            boxes.append(box); info[role] = tier

        tex, tex_tier = self._texture_boxes(mask, G, W, H, mask_tier)
        for i, b in enumerate(tex):
            boxes.append(b); info[f"tex{i}"] = tex_tier if b is not None else "none"

        patches, coords, valid = [], np.zeros((NUM_PATCHES, 5), np.float32), np.zeros(NUM_PATCHES, bool)
        for i, b in enumerate(boxes):
            res = None if b is None else self._crop_square(img, b)
            if res is None:
                patches.append(None)
                continue
            sq, (x1, y1, x2, y2) = res
            patches.append(sq)
            coords[i] = [x1 / W, y1 / H, x2 / W, y2 / H, ((x2 - x1) * (y2 - y1)) / (W * H)]
            valid[i] = True
        valid[0] = True  # global patch is always valid
        return patches, coords, valid, info

    # inputs
    @staticmethod
    def _get_mask(parse, W, H):
        if parse is None or parse.mask is None:
            return None
        m = np.asarray(parse.mask).astype(np.uint8)
        if m.shape != (H, W):
            m = np.array(Image.fromarray(m * 255).resize((W, H), Image.NEAREST)) > 0
            m = m.astype(np.uint8)
        m = m.astype(bool)
        return m if m.sum() >= 0.01 * W * H else None  # ignore degenerate masks

    @staticmethod
    def _get_keypoints(parse, W, H):
        if parse is None or parse.keypoints is None or len(parse.keypoints) == 0:
            return None
        kp = np.asarray(parse.keypoints, np.float32).copy()
        outside = (kp[:, 0] < 0) | (kp[:, 0] >= W) | (kp[:, 1] < 0) | (kp[:, 1] >= H)
        kp[outside, 2] = 0
        return kp

    @staticmethod
    def _hull_mask(kp, W, H):
        pts = kp[kp[:, 2] >= 1, :2]
        if len(pts) < 4:
            return None
        hull = cv2.convexHull(pts.astype(np.float32)).astype(np.int32)
        m = np.zeros((H, W), np.uint8)
        cv2.fillPoly(m, [hull], 1)
        m = m.astype(bool)
        return m if m.sum() >= 0.01 * W * H else None

    @staticmethod
    def _garment_box(mask, kp, parse, W, H):
        if mask is not None:
            ys, xs = np.where(mask)
            box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
        elif kp is not None and (kp[:, 2] >= 1).sum() >= 3:
            p = kp[kp[:, 2] >= 1]
            x1, y1, x2, y2 = p[:, 0].min(), p[:, 1].min(), p[:, 0].max(), p[:, 1].max()
            px, py = 0.05 * (x2 - x1), 0.05 * (y2 - y1)
            box = (max(0, x1 - px), max(0, y1 - py), min(W, x2 + px), min(H, y2 + py))
        elif parse is not None and parse.bbox is not None:
            box = parse.bbox
        else:
            box = (0, 0, W, H)
        x1, y1, x2, y2 = [float(v) for v in box]
        if x2 - x1 < 8 or y2 - y1 < 8:
            return (0.0, 0.0, float(W), float(H))
        return (x1, y1, x2, y2)

    def _suppress_background(self, img, mask):
        k = max(3, int(0.01 * max(img.size)) | 1)
        m = cv2.dilate(mask.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
        arr = np.array(img)
        arr[~m] = FILL_RGB
        return Image.fromarray(arr)

    # upper_boundary / side / hem
    def _from_keypoints(self, role, category, kp, G):
        if kp is None:
            return None, "proportion"
        pts, tier = None, None
        groups = LANDMARK_GROUPS.get(category.lower(), {})
        spec = groups.get(role)
        if spec:
            cands = spec if isinstance(spec[0], list) else [spec]
            best = []
            for cand in cands:
                idx = [i for i in cand if i < len(kp) and kp[i, 2] >= 1]
                if (len(idx), sum(kp[i, 2] == 2 for i in idx)) > (len(best), sum(kp[i, 2] == 2 for i in best)):
                    best = idx
            if len(best) >= self.MIN_KP:
                pts, tier = kp[best, :2], "table"
        if pts is None:
            sp = self._spatial_group(role, category, kp, G)
            if sp is not None and len(sp) >= self.MIN_KP:
                pts, tier = sp, "spatial"
        if pts is None:
            return None, "proportion"
        return self._points_to_box(pts, G), tier

    @staticmethod
    def _spatial_group(role, category, kp, G):
        """Index-free grouping of keypoints by where they lie inside the garment box."""
        vis2, vis = kp[kp[:, 2] == 2], kp[kp[:, 2] >= 1]
        use = vis2 if len(vis2) >= 6 else vis
        if len(use) < 4:
            return None
        gx1, gy1, gx2, gy2 = G
        rx = (use[:, 0] - gx1) / (gx2 - gx1)
        ry = (use[:, 1] - gy1) / (gy2 - gy1)
        bottom = slot_config(category)[0] == "bottom"
        if role == "upper_boundary":
            sel = (ry <= 0.15) if bottom else ((ry <= 0.22) & (rx >= 0.25) & (rx <= 0.75))
        elif role == "hem":
            sel = ry >= (0.9 if bottom else 0.85)
        elif role == "side":
            if bottom:
                left, right = (rx <= 0.4) & (ry >= 0.5), (rx >= 0.6) & (ry >= 0.5)
            else:
                left, right = rx <= 0.18, rx >= 0.82
            sel = left if left.sum() >= right.sum() else right
        else:
            return None
        return use[sel, :2]

    def _points_to_box(self, pts, G):
        x1, y1 = pts.min(0)
        x2, y2 = pts.max(0)
        ref = max(G[2] - G[0], G[3] - G[1])
        side = max((x2 - x1) * (1 + self.KP_EXPAND), (y2 - y1) * (1 + self.KP_EXPAND), self.KP_MIN_FRAC * ref)
        side = min(side, self.KP_MAX_FRAC * ref)
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        return (cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)

    @staticmethod
    def _from_proportions(role, category, G):
        fam, _ = slot_config(category)
        px1, py1, px2, py2 = (_PROP_LOWER if fam == "bottom" else _PROP_UPPER)[role]
        gx1, gy1, gx2, gy2 = G
        gw, gh = gx2 - gx1, gy2 - gy1
        return (gx1 + px1 * gw, gy1 + py1 * gh, gx1 + px2 * gw, gy1 + py2 * gh)

    # texture
    def _texture_boxes(self, mask, G, W, H, tier="mask", n=4):
        gw, gh = G[2] - G[0], G[3] - G[1]
        s = max(24.0, 0.2 * float(np.sqrt(gw * gh)))
        boxes: List[Optional[Tuple[float, float, float, float]]] = []

        if mask is not None:
            scale = min(1.0, 256.0 / max(W, H))
            m = mask.astype(np.uint8)
            if scale < 1.0:
                m = cv2.resize(m, (max(1, int(W * scale)), max(1, int(H * scale))), interpolation=cv2.INTER_NEAREST)
            sw = max(3, int(round(s * scale))) | 1
            cov = cv2.boxFilter(m.astype(np.float32), -1, (sw, sw), normalize=True, borderType=cv2.BORDER_CONSTANT)
            dist = cv2.distanceTransform(m, cv2.DIST_L2, 3)
            picked: List[Tuple[int, int]] = []
            for thr in (self.texture_coverage, 0.85):
                score = np.where((cov >= thr) & (m > 0), dist, 0).astype(np.float32)
                for py, px in picked:
                    score[max(0, py - sw): py + sw + 1, max(0, px - sw): px + sw + 1] = 0
                while len(picked) < n and score.max() > 0:
                    y, x = np.unravel_index(int(score.argmax()), score.shape)
                    picked.append((int(y), int(x)))
                    score[max(0, y - sw): y + sw + 1, max(0, x - sw): x + sw + 1] = 0
                if len(picked) >= n:
                    break
            for y, x in picked:
                cx, cy = x / scale, y / scale
                boxes.append((cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2))
            boxes += [None] * (n - len(boxes))
            return boxes, tier

        for rx, ry in _TEX_CENTERS[:n]:
            cx, cy = G[0] + rx * gw, G[1] + ry * gh
            boxes.append((cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2))
        return boxes, "proportion"

    # ------------------------------------------------------------------ cropping
    @staticmethod
    def _crop_square(img: Image.Image, box):
        """Square crop around the box centre; areas outside the image are filled with the mean colour.

        Returns (square, final_box): final_box is the square in image pixels, INCLUDING the
        padded part (it may exceed the image). Coords must describe this square, not the
        intersected region, so the spatial embedding matches the backbone input.
        """
        W, H = img.size
        x1, y1, x2, y2 = box
        side = int(max(16, round(max(x2 - x1, y2 - y1))))
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        sx, sy = int(round(cx - side / 2)), int(round(cy - side / 2))
        ix1, iy1, ix2, iy2 = max(0, sx), max(0, sy), min(W, sx + side), min(H, sy + side)
        if ix2 - ix1 < 8 or iy2 - iy1 < 8:
            return None
        canvas = Image.new("RGB", (side, side), FILL_RGB)
        canvas.paste(img.crop((ix1, iy1, ix2, iy2)), (ix1 - sx, iy1 - sy))
        return canvas, (sx, sy, sx + side, sy + side)

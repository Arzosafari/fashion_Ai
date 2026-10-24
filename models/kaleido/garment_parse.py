# garment_parse.py
"""
Result of garment parsing (keypoints + pixel mask) in the coordinate frame of the
image that is given to SemanticKPG (i.e. the crop produced by cropper.py).

It can be produced either by:
  * a model (Match R-CNN / Mask R-CNN with a keypoint head / YOLO-seg + pose) run OFFLINE
    and cached with GarmentParse.save(), or
  * the DeepFashion2 ground-truth annotation (GarmentParse.from_deepfashion2_item),
    which is useful for training.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple, Sequence

import numpy as np
from PIL import Image, ImageDraw

# DeepFashion2 category order (category_id 1..13)
DF2_CATEGORIES = [
    "short sleeve top", "long sleeve top", "short sleeve outwear", "long sleeve outwear",
    "vest", "sling", "shorts", "trousers", "skirt",
    "short sleeve dress", "long sleeve dress", "vest dress", "sling dress",
]
# Number of landmarks of each category (they sum to 294). VERIFY against the official
# DeepFashion2 landmark definition before using them to slice a 294-dim keypoint head.
DF2_LANDMARK_COUNTS = [25, 33, 31, 39, 15, 15, 10, 14, 8, 29, 37, 19, 19]
assert sum(DF2_LANDMARK_COUNTS) == 294


def category_name_from_id(category_id: int) -> str:
    """1-based DeepFashion2 category id -> name. Invalid ids raise (never wrap around)."""
    cid = int(category_id)
    if not 1 <= cid <= len(DF2_CATEGORIES):
        raise ValueError(f"DeepFashion2 category_id must be 1..13; got {category_id!r}")
    return DF2_CATEGORIES[cid - 1]


def category_id_from_name(category: str) -> int:
    """DeepFashion2 category name -> 1-based id (accepts legacy family names too)."""
    name = str(category).strip().lower().replace("_", " ")
    if name in DF2_CATEGORIES:
        return DF2_CATEGORIES.index(name) + 1
    legacy = {"top": 1, "outerwear": 4, "bottom": 8, "dress": 10}
    if name in legacy:
        return legacy[name]
    raise ValueError(f"unknown DeepFashion2 category: {category!r}")


def category_keypoint_slice(category_id: int) -> slice:
    """Slice of the 294-dim DeepFashion2 keypoint head that belongs to this category."""
    cid = int(category_id)
    if not 1 <= cid <= len(DF2_LANDMARK_COUNTS):
        raise ValueError(f"DeepFashion2 category_id must be 1..13; got {category_id!r}")
    start = int(sum(DF2_LANDMARK_COUNTS[:cid - 1]))
    return slice(start, start + DF2_LANDMARK_COUNTS[cid - 1])


def _as_polygons(seg) -> list:
    """Segmentation field -> list of polygons. A flat list of NUMBERS is one polygon."""
    if seg is None:
        return []
    if isinstance(seg, list) and seg and all(isinstance(v, (int, float)) for v in seg):
        return [seg]
    return seg if isinstance(seg, list) else [seg]


@dataclass
class GarmentParse:
    category: str                                   # DeepFashion2 name, e.g. "long sleeve top"
    keypoints: Optional[np.ndarray] = None          # [K, 3] = (x, y, v); v: 0 absent, 1 occluded, 2 visible
    mask: Optional[np.ndarray] = None               # [H, W] bool, garment pixels (visible fabric only)
    bbox: Optional[Tuple[float, float, float, float]] = None  # x1, y1, x2, y2

    # validation 
    def validate(self, image_size: Tuple[int, int], require_mask: bool = False,
                 require_keypoints: bool = False) -> "GarmentParse":
        """Check that mask, keypoints and bbox share one crop frame (width, height).

        Out-of-frame or non-finite keypoints are demoted to v=0 (their coordinates
        are zeroed); missing data raises only when it was explicitly required.
        """
        w, h = map(int, image_size)
        if w <= 0 or h <= 0:
            raise ValueError(f"invalid image_size={image_size}")
        if self.mask is not None:
            m = np.asarray(self.mask)
            if m.ndim != 2 or m.shape != (h, w):
                raise ValueError(f"mask must have shape {(h, w)} in crop coordinates; got {m.shape}")
            self.mask = m.astype(bool, copy=False)
        elif require_mask:
            raise ValueError("a real segmentation mask is required but GarmentParse.mask is None")
        if self.keypoints is not None:
            kp = np.asarray(self.keypoints, dtype=np.float32).copy()
            if kp.ndim != 2 or kp.shape[1] != 3:
                raise ValueError(f"keypoints must have shape [K,3], got {kp.shape}")
            bad = ~np.isfinite(kp).all(axis=1)
            bad |= (kp[:, 0] < 0) | (kp[:, 0] >= w) | (kp[:, 1] < 0) | (kp[:, 1] >= h)
            bad |= ~np.isin(kp[:, 2], [0, 1, 2])
            kp[bad, 2] = 0
            kp[kp[:, 2] == 0, :2] = 0
            self.keypoints = kp
            if require_keypoints and not np.any(kp[:, 2] > 0):
                raise ValueError("landmark model returned no valid keypoints")
        elif require_keypoints:
            raise ValueError("landmark model returned no keypoints")
        if self.bbox is not None:
            if len(self.bbox) != 4 or not np.isfinite(self.bbox).all():
                raise ValueError(f"bbox must be finite XYXY, got {self.bbox!r}")
            x1, y1, x2, y2 = map(float, self.bbox)
            if x2 <= x1 or y2 <= y1:
                raise ValueError(f"bbox must have positive area, got {self.bbox!r}")
        return self

    # cache I/O 
    def save(self, path: str) -> None:
        np.savez_compressed(
            path,
            category=np.array(self.category),
            keypoints=np.zeros((0, 3), np.float32) if self.keypoints is None else self.keypoints.astype(np.float32),
            mask=np.zeros((0, 0), bool) if self.mask is None else self.mask.astype(bool),
            bbox=np.zeros((0,), np.float32) if self.bbox is None else np.asarray(self.bbox, np.float32),
        )

    @staticmethod
    def load(path: str) -> "GarmentParse":
        d = np.load(path, allow_pickle=False)
        kp, mk, bb = d["keypoints"], d["mask"], d["bbox"]
        return GarmentParse(
            category=str(d["category"]),
            keypoints=kp if kp.size else None,
            mask=mk if mk.size else None,
            bbox=tuple(float(v) for v in bb) if bb.size else None,
        )

    # DeepFashion2 ground truth 
    @staticmethod
    def from_deepfashion2_item(
        item: dict,
        image_size: Tuple[int, int],
        origin: Tuple[float, float] = (0.0, 0.0),
    ) -> "GarmentParse":
        """
        item: one garment entry of a DeepFashion2 annotation json
              (keys: category_id, landmarks, segmentation, bounding_box).
        image_size: (width, height) of the image KPG will receive (the crop).
        origin: (x0, y0) of that crop inside the original photo
                (use GarmentCropper.crop_region_with_origin).
        """
        w, h = map(int, image_size)
        ox, oy = map(float, origin)
        name = category_name_from_id(item["category_id"])

        kp = None
        lm = np.asarray(item.get("landmarks", []), dtype=np.float32)
        if lm.size and lm.size % 3 == 0:
            kp = lm.reshape(-1, 3).copy()
            kp[:, 0] -= ox
            kp[:, 1] -= oy
            invalid = (
                ~np.isfinite(kp).all(axis=1)
                | (kp[:, 0] < 0) | (kp[:, 0] >= w)
                | (kp[:, 1] < 0) | (kp[:, 1] >= h)
                | ~np.isin(kp[:, 2], [0, 1, 2])
            )
            kp[invalid, 2] = 0
            kp[kp[:, 2] == 0, :2] = 0

        canvas = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(canvas)
        has_poly = False
        for poly in _as_polygons(item.get("segmentation")):
            try:
                pts = np.asarray(poly, dtype=np.float32).reshape(-1, 2)
            except (TypeError, ValueError):
                continue  # malformed polygon: skip it, never crash the whole row
            if len(pts) >= 3 and np.isfinite(pts).all():
                pts = pts - np.array([ox, oy], np.float32)
                draw.polygon([tuple(p) for p in pts], fill=1)
                has_poly = True
        mask = np.array(canvas, dtype=bool) if has_poly else None

        bbox = None
        raw_box = item.get("bounding_box", item.get("bbox"))
        if raw_box is not None and len(raw_box) >= 4:
            x1, y1, x2, y2 = (float(v) for v in raw_box[:4])
            if x2 > x1 and y2 > y1:
                bbox = (x1 - ox, y1 - oy, x2 - ox, y2 - oy)

        return GarmentParse(category=name, keypoints=kp, mask=mask, bbox=bbox).validate((w, h))

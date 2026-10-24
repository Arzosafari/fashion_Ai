# yolo_segmenter.py
"""
Exact fabric masks at inference time with a fine-tuned YOLO26-seg model.

Why: the landmark parser (Keypoint R-CNN) predicts boxes + keypoints but no
pixel mask, so Semantic-KPG falls back to a convex-hull approximation ("hull"
tier). A YOLO-seg model trained on the 13 DeepFashion2 categories returns the
exact fabric mask, which unlocks the "mask" tier at inference (background
suppression + texture windows fully inside the fabric).

Training labels come from df2_pipeline/csv_to_yolo_seg.py (Train.csv -> YOLO-seg dataset).
Class order is the DeepFashion2 order, 0-based: class c == category_id c + 1.

Usage:
    seg = YoloSegmenter(weights="runs/segment/train/weights/best.pt")
    parse.mask = seg.segment_crop(crop, category_id)  # (H, W) bool, or None
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image

try:
    from model.kaleido.garment_parse import DF2_CATEGORIES
except ImportError:
    from garment_parse import DF2_CATEGORIES


def _norm_name(name: str) -> str:
    return " ".join(str(name).lower().replace("_", " ").replace("-", " ").split())


def _to_numpy(x) -> np.ndarray:
    return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)


def pick_best_index(classes: np.ndarray, scores: np.ndarray,
                    expected_cls: Optional[int]) -> Optional[int]:
    """Index of the highest-score detection of the expected class.

    If expected_cls is None, the best detection of any class wins.
    Returns None when there is no detection (of that class).
    """
    classes = np.asarray(classes).astype(int).ravel()
    scores = np.asarray(scores).astype(float).ravel()
    if len(classes) != len(scores):
        raise ValueError(f"classes/scores length mismatch: {len(classes)} != {len(scores)}")
    idx = np.arange(len(scores))
    if expected_cls is not None:
        idx = idx[classes == int(expected_cls)]
    if len(idx) == 0:
        return None
    return int(idx[int(np.argmax(scores[idx]))])


class YoloSegmenter:
    def __init__(self, weights: str, conf: float = 0.25, device=None):
        from ultralytics import YOLO  # lazy: only needed where the weights run
        if not weights:
            raise ValueError("Provide a fine-tuned DeepFashion2 YOLO-seg checkpoint; COCO yolo*-seg weights are not compatible")
        self.model = YOLO(weights)
        self.conf = float(conf)
        self.device = device
        names = self.model.names
        pairs = [(int(k), v) for k, v in names.items()] if isinstance(names, dict) else list(enumerate(names))
        lookup = {_norm_name(name): i + 1 for i, name in enumerate(DF2_CATEGORIES)}
        self.class_to_category = {int(i): lookup[_norm_name(name)] for i, name in pairs
                                  if _norm_name(name) in lookup}
        if len(self.class_to_category) != 13:
            raise ValueError(
                "Segmentation checkpoint must expose all 13 DeepFashion2 class names in the expected taxonomy. "
                f"Model names were: {names!r}"
            )
        self.category_to_class = {cid: cls for cls, cid in self.class_to_category.items()}

    def segment_crop(self, crop: Image.Image,
                     category_id: Optional[int] = None) -> Optional[np.ndarray]:
        """Exact fabric mask of the garment inside the crop.

        Args:
            crop: the garment crop (the same image the parser receives).
            category_id: 1-based DeepFashion2 id from the detector; only masks
                of this class are accepted, so a neighbour garment inside the
                crop can never steal the mask. None accepts any class.
        Returns:
            (H, W) bool mask in crop coordinates, or None when the model finds
            nothing usable (the planner then falls back to the hull tier).
        """
        result = self._predict(crop)
        masks = getattr(result, "masks", None)
        boxes = getattr(result, "boxes", None)
        if masks is None or boxes is None or len(boxes) == 0:
            return None
        data = _to_numpy(masks.data)  # (N, H, W)
        if data.ndim != 3 or len(data) == 0:
            return None
        if category_id is not None and not 1 <= int(category_id) <= 13:
            raise ValueError(f"category_id must be 1..13; got {category_id!r}")
        expected = self.category_to_class[int(category_id)] if category_id is not None else None
        i = pick_best_index(_to_numpy(boxes.cls), _to_numpy(boxes.conf), expected)
        if i is None or i >= len(data):
            return None
        m = np.asarray(data[i]) >= 0.5
        W, H = crop.size
        if m.shape != (H, W):
            raise ValueError(f"YOLO segmentation mask shape {m.shape} does not match crop {(H, W)}. "
                             "Keep retina_masks=True and verify the Ultralytics version/configuration.")
        return m if m.sum() >= 0.01 * W * H else None

    def _predict(self, crop: Image.Image):
        """One forward pass; returns the ultralytics Result of the crop."""
        return self.model.predict(source=crop, conf=self.conf,
                                  retina_masks=True, verbose=False,
                                  device=self.device)[0]

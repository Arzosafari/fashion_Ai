# garment_detector.py
"""Ultralytics YOLO detector adapter; maps YOLO's 0-based class ids to DF2's 1-based ids."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np
from PIL import Image

from model.kaleido.garment_parse import DF2_CATEGORIES



def _norm_name(name: str) -> str:
    return " ".join(str(name).lower().replace("_", " ").replace("-", " ").split())

def _to_numpy(x) -> np.ndarray:
    return x.detach().cpu().numpy() if hasattr(x, "detach") else np.asarray(x)


@dataclass(frozen=True)
class GarmentDetection:
    category_id: int
    score: float
    bbox_xyxy: tuple


class YoloGarmentDetector:
    """Garment detector from YOLO26 weights fine-tuned on the 13 DeepFashion2 categories.

    weights: path to the fine-tuned checkpoint. Plain COCO weights are rejected with
    a clear error (they do not expose the 13 DeepFashion2 class names).
    """

    def __init__(self, weights: str = "yolo26n.pt", conf: float = 0.25, device=None):
        from ultralytics import YOLO
        if not 0.0 <= conf <= 1.0:
            raise ValueError("conf must be in [0,1]")
        self.model = YOLO(weights)
        self.conf = float(conf)
        self.device = device
        names = self.model.names
        if isinstance(names, dict):
            pairs = [(int(k), v) for k, v in names.items()]
        else:
            pairs = list(enumerate(names))
        lookup = {_norm_name(name): i + 1 for i, name in enumerate(DF2_CATEGORIES)}
        self.class_to_category = {int(i): lookup[_norm_name(name)] for i, name in pairs
                                  if _norm_name(name) in lookup}
        if len(self.class_to_category) != 13:
            raise ValueError(
                "Detector checkpoint must expose all 13 DeepFashion2 class names in the expected taxonomy. "
                f"Model names were: {names!r}"
            )

    def detect(self, image: Image.Image, category_id: Optional[int] = None) -> List[GarmentDetection]:
        detections, _ = self.detect_with_masks(image, category_id=category_id)
        return detections

    def detect_with_masks(self, image: Image.Image,
                          category_id: Optional[int] = None
                          ) -> tuple[List[GarmentDetection], List[Optional[np.ndarray]]]:
        """Detect garments and return full-image masks aligned with the detections.

        The model runs ONCE on the full image; masks[i] belongs to
        detections[i] (same forward pass, no matching needed). masks[i] is
        None when the checkpoint is detect-only.
        """
        rgb = image.convert("RGB")
        W, H = rgb.size
        result = self.model.predict(source=rgb, conf=self.conf, retina_masks=True,
                                    verbose=False, device=self.device)[0]
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return [], []
        masks = getattr(result, "masks", None)
        data = _to_numpy(masks.data) if masks is not None else None
        if data is not None and (data.ndim != 3 or data.shape[0] != len(boxes)):
            data = None  # misaligned output: treat as detect-only
        xyxy = _to_numpy(boxes.xyxy)
        cls = _to_numpy(boxes.cls).astype(int)
        conf = _to_numpy(boxes.conf)
        pairs = []
        for i, (b, c, s) in enumerate(zip(xyxy, cls, conf)):
            if int(c) not in self.class_to_category:
                continue
            cid = self.class_to_category[int(c)]
            if not 1 <= cid <= 13 or (category_id is not None and cid != int(category_id)):
                continue
            x1, y1, x2, y2 = map(float, b)
            if x2 <= x1 or y2 <= y1:
                continue
            m = None
            if data is not None:
                m = np.asarray(data[i]) >= 0.5
                if m.shape != (H, W):
                    m = None
            pairs.append((GarmentDetection(cid, float(s), (x1, y1, x2, y2)), m))
        pairs.sort(key=lambda p: p[0].score, reverse=True)
        return [p[0] for p in pairs], [p[1] for p in pairs]
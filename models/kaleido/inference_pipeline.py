# inference_pipeline.py
"""End-to-end inference: detector -> crop -> caption + landmarks + mask -> SemanticKPG -> embedding."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image


from model.vision.cropper import GarmentCropper



from model.kaleido.garment_parse import GarmentParse, category_name_from_id, DF2_LANDMARK_COUNTS
from model.kaleido.garment_detector import YoloGarmentDetector, GarmentDetection
from model.kaleido.df2_keypoint_rcnn import DF2KeypointRCNN
from model.kaleido.yolo_segmenter import YoloSegmenter
from model.kaleido.semantic_kaleido_model import SemanticKaleidoBERT



@dataclass
class EmbeddedGarment:
    detection: GarmentDetection
    crop: Image.Image
    crop_origin: tuple
    parse: GarmentParse
    embedding: Any
    caption: str = "" 


class InferenceComponentError(RuntimeError):
    """Raised instead of silently substituting a fake mask or mismatched landmarks."""


def _slice_full_mask(full_mask: Optional[np.ndarray], origin: tuple, size: tuple) -> Optional[np.ndarray]:
    """Slice a full-image (H, W) bool mask to a crop window.

    Returns None when there is no usable full-image mask (caller falls back
    to segmenting the crop).
    """
    if full_mask is None:
        return None
    m = np.asarray(full_mask).astype(bool)
    ox, oy = int(origin[0]), int(origin[1])
    cw, ch = int(size[0]), int(size[1])
    H, W = m.shape[:2]
    x0, y0 = max(ox, 0), max(oy, 0)
    x1, y1 = min(ox + cw, W), min(oy + ch, H)
    if x1 <= x0 or y1 <= y0:
        return None
    out = np.zeros((ch, cw), dtype=bool)
    out[y0 - oy:y1 - oy, x0 - ox:x1 - ox] = m[y0:y1, x0:x1]
    return out


def _shift_keypoints(keypoints: Any, origin: tuple) -> Optional[np.ndarray]:
    """Shift (K, 3) full-image keypoints into crop coordinates.

    Returns None when the model returned no keypoints.
    """
    if keypoints is None:
        return None
    k = np.asarray(keypoints, dtype=float).reshape(-1, 3).copy()
    ox, oy = float(origin[0]), float(origin[1])
    k[:, 0] -= ox
    k[:, 1] -= oy
    return k

class GarmentInferencePipeline:
    def __init__(self, detector: YoloGarmentDetector, landmark_model: Optional[DF2KeypointRCNN],
                 segmenter: YoloSegmenter, embedding_model: SemanticKaleidoBERT,
                 captioner: Any = None,
                 cropper: Optional[GarmentCropper] = None, padding_pct: float = 0.05,
                 require_mask: bool = True, require_keypoints: bool = True):
        self.detector = detector
        self.landmark_model = landmark_model  # None = no landmark model yet (keypoints stay empty)
        self.segmenter = segmenter
        self.embedding_model = embedding_model
        self.captioner = captioner  # None = caller passes free_text; set = auto-caption each crop
        self.cropper = cropper or GarmentCropper()
        self.padding_pct = float(padding_pct)
        self.require_mask = bool(require_mask)
        self.require_keypoints = bool(require_keypoints)
        if self.padding_pct < 0:
            raise ValueError("padding_pct must be >= 0")

    @staticmethod
    def _load_image(image: Any) -> Image.Image:
        if isinstance(image, Image.Image):
            return image.convert("RGB")
        if isinstance(image, (str, os.PathLike)):
            with Image.open(image) as im:
                return im.convert("RGB")
        raise TypeError("image must be a PIL image or filesystem path")

    def embed_all(self, image: Any, llm_metadata: Optional[Dict[str, Any]] = None,
                  free_text: str = "", category_id: Optional[int] = None,
                  max_detections: Optional[int] = None) -> List[EmbeddedGarment]:
        full_image = self._load_image(image)
        if hasattr(self.detector, "detect_with_masks"):
            detections, full_masks = self.detector.detect_with_masks(full_image, category_id=category_id)
        else:  # detector adapter without mask support: crop fallback below
            detections = self.detector.detect(full_image, category_id=category_id)
            full_masks = [None] * len(detections)
        if max_detections is not None:
            if max_detections < 1:
                raise ValueError("max_detections must be positive or None")
            detections = detections[:max_detections]
            full_masks = full_masks[:max_detections]
        if not detections:
            raise InferenceComponentError("Detector returned no garment detections")

        outputs: List[EmbeddedGarment] = []
        metadata = llm_metadata or {}
        outputs: List[EmbeddedGarment] = []
        metadata = llm_metadata or {}
        kp_cache: Dict[int, GarmentParse] = {}  # category_id -> full-image parse
        for det, full_mask in zip(detections, full_masks):
            crop, (ox, oy) = self.cropper.crop_region_with_origin(
                full_image, det.bbox_xyxy, padding_pct=self.padding_pct)
            cw, ch = crop.size
            # Convert the detector's original-image XYXY box to the crop coordinate frame.
            bx1, by1, bx2, by2 = det.bbox_xyxy
            local_bbox = (max(0.0, bx1 - ox), max(0.0, by1 - oy),
                          min(float(cw), bx2 - ox), min(float(ch), by2 - oy))
            if local_bbox[2] <= local_bbox[0] or local_bbox[3] <= local_bbox[1]:
                raise InferenceComponentError("Detector bbox became degenerate after cropping")

            # The landmark model is run on exactly the crop that SemanticKPG will receive.
            # None = no landmark model yet: keypoints stay empty, the mask carries the geometry.
            if self.landmark_model is None:
                kp_parse = GarmentParse(category=category_name_from_id(det.category_id))
            else:
                if det.category_id not in kp_cache:
                    kp_cache[det.category_id] = self.landmark_model.predict_parse(
                        full_image, category_id=det.category_id)
                full_parse = kp_cache[det.category_id]
                kp_parse = GarmentParse(category=full_parse.category,keypoints=_shift_keypoints(full_parse.keypoints, (ox, oy)),)
                if kp_parse.keypoints is None:
                    # Fallback: previous behavior (predict on the crop).
                    kp_parse = self.landmark_model.predict_parse(crop, category_id=det.category_id)
            if kp_parse.category != category_name_from_id(det.category_id):
                raise InferenceComponentError(
                    f"Landmark category mismatch: expected {category_name_from_id(det.category_id)!r}, "
                    f"got {kp_parse.category!r}")
            expected_k = DF2_LANDMARK_COUNTS[det.category_id - 1]
            if kp_parse.keypoints is not None and len(kp_parse.keypoints) != expected_k:
                raise InferenceComponentError(
                    f"Landmark count mismatch for category {det.category_id}: "
                    f"expected {expected_k}, got {len(kp_parse.keypoints)}")
            # Primary: slice the full-image mask (same forward pass as the box).
            # Tiny crops are OOD for the seg model, so re-running segmentation
            # on the crop fails even when the full image segments fine.
            mask = _slice_full_mask(full_mask, (ox, oy), (cw, ch))
            if mask is None:
                # Fallback: previous behavior (re-run seg on the crop).
                mask = self.segmenter.segment_crop(crop, category_id=det.category_id)
            if mask is not None and int(np.asarray(mask).sum()) < 0.01 * cw * ch:
                mask = None
            parse = GarmentParse(
                category=category_name_from_id(det.category_id),
                keypoints=kp_parse.keypoints,
                mask=mask,
                bbox=local_bbox,
            )
            try:
                parse.validate((cw, ch), require_mask=self.require_mask,
                               require_keypoints=self.require_keypoints)
            except ValueError as exc:
                raise InferenceComponentError(
                    f"Invalid detector/landmark/segmentation output for category "
                    f"{det.category_id} in crop {(cw, ch)}: {exc}") from exc

            # Both keypoints and mask are already in crop coordinates. Do not shift them again.
            # The parse was strictly validated above, which is what require_parse=True meant.
            if free_text:
                text = free_text
            elif self.captioner is not None:
                text = self.captioner.analyze_garment(crop, parse.category)
            else:
                text = ""
            embedding = self.embedding_model.extract_embedding(
                image=crop,
                llm_metadata=metadata,
                free_text=text,
                category=parse.category,
                parse=parse,
            )
            outputs.append(EmbeddedGarment(det, crop, (ox, oy), parse, embedding, text))
        return outputs

    def embed_one(self, image: Any, llm_metadata: Optional[Dict[str, Any]] = None,
                  free_text: str = "", category_id: Optional[int] = None,
                  detection_index: int = 0) -> EmbeddedGarment:
        items = self.embed_all(image, llm_metadata, free_text, category_id)
        if detection_index < 0 or detection_index >= len(items):
            raise IndexError(f"detection_index {detection_index} out of range for {len(items)} detections")
        return items[detection_index]

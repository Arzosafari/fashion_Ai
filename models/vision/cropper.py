# vision/cropper.py
"""Garment cropping with a safety margin.

Coordinate contract: landmarks and masks are shifted by the crop origin into
the crop frame WITHOUT rescaling. Semantic-KPG therefore cuts patches from the
very same crop pixels (it resizes patches, never the crop). If you ever resize
a crop before planning, rescale the points with scale_points() first, otherwise
keypoints and pixels silently drift apart.
"""
import math
from PIL import Image
from typing import List, Sequence, Tuple, Union

import numpy as np


def validate_bbox(bbox: Sequence, img_w: int, img_h: int, padding_pct: float) -> List[float]:
    """Reject broken boxes loudly instead of producing an empty crop downstream."""
    vals = list(bbox) if isinstance(bbox, (list, tuple, np.ndarray)) else None
    if vals is None or len(vals) != 4:
        raise ValueError(f"bbox must hold exactly 4 numbers, got {bbox!r}")
    try:
        xmin, ymin, xmax, ymax = [float(v) for v in vals]
    except (TypeError, ValueError):
        raise ValueError(f"bbox holds non-numeric values: {bbox!r}")
    if not all(math.isfinite(v) for v in (xmin, ymin, xmax, ymax)):
        raise ValueError(f"bbox holds NaN/inf: {bbox!r}")
    if not (xmax > xmin and ymax > ymin):
        raise ValueError(f"bbox has no positive area: {bbox!r}")
    if not (0.0 <= float(padding_pct) <= 0.5):
        raise ValueError(f"padding_pct must be in [0, 0.5], got {padding_pct!r}")
    if not (img_w > 0 and img_h > 0):
        raise ValueError(f"bad image size: {(img_w, img_h)}")
    return [xmin, ymin, xmax, ymax]


def scale_points(points_xy: np.ndarray, from_size: Tuple[int, int],
                 to_size: Tuple[int, int]) -> np.ndarray:
    """Rescale (x, y) points when an image changes size (crop -> resized input)."""
    fw, fh = from_size
    tw, th = to_size
    out = np.asarray(points_xy, dtype=np.float64).copy()
    out[..., 0] *= tw / fw
    out[..., 1] *= th / fh
    return out


class GarmentCropper:
    """Crop YOLO detections (5% margin) + report the crop origin."""

    @staticmethod
    def padded_box(img_w: int, img_h: int, bbox: List[int],
                   padding_pct: float = 0.05) -> List[int]:
        """Final box with safety margin, clipped to the image.

        Lower edges use floor, upper edges ceil, so border pixels survive.
        """
        xmin, ymin, xmax, ymax = validate_bbox(bbox, img_w, img_h, padding_pct)
        pad_w = (xmax - xmin) * padding_pct
        pad_h = (ymax - ymin) * padding_pct
        box = [int(math.floor(max(0, xmin - pad_w))), int(math.floor(max(0, ymin - pad_h))),
               int(math.ceil(min(img_w, xmax + pad_w))), int(math.ceil(min(img_h, ymax + pad_h)))]
        if not (box[2] > box[0] and box[3] > box[1]):
            raise ValueError(f"bbox {bbox!r} leaves no visible area in a {(img_w, img_h)} image")
        return box

    @staticmethod
    def crop_region_with_origin(
        image_input: Union[str, Image.Image],
        bbox: List[int],
        padding_pct: float = 0.05
    ) -> Tuple[Image.Image, Tuple[int, int]]:
        """Crop + (x0, y0): top-left corner of the crop in the original photo.

        The origin shifts keypoints / masks into the crop frame.
        """
        if isinstance(image_input, str):
            with Image.open(image_input) as f:  # caller-owned Images are never closed
                img = f.convert("RGB")
        else:
            img = image_input.convert("RGB")
        w, h = img.size
        x1, y1, x2, y2 = GarmentCropper.padded_box(w, h, bbox, padding_pct)
        return img.crop((x1, y1, x2, y2)), (x1, y1)

    @staticmethod
    def crop_region(
        image_input: Union[str, Image.Image],
        bbox: List[int],
        padding_pct: float = 0.05
    ) -> Image.Image:
        """Crop a garment box. Output feeds the Kaleido model."""
        return GarmentCropper.crop_region_with_origin(image_input, bbox, padding_pct)[0]


if __name__ == "__main__":
    test_img = Image.new("RGB", (500, 500), color="white")
    cropped, origin = GarmentCropper.crop_region_with_origin(test_img, [50, 50, 200, 300])
    print(f"[GarmentCropper] crop OK: {cropped.size} origin={origin}")

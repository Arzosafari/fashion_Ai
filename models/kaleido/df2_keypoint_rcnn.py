# df2_keypoint_rcnn.py
"""
Garment landmark model for DeepFashion2 (what the DeepFashion2 paper calls the Match R-CNN landmark branch).

IMPORTANT - what this really is:
  Backend = torchvision Keypoint R-CNN. It has box + class + keypoint heads but NO mask head and NO
  matching branch, so it is *not* Match R-CNN. Its output is a GarmentParse WITHOUT a mask
  (the KPG approximates the fabric region from the landmarks).
  No pretrained DeepFashion2 weights exist: fine-tune it once (see below).

Keypoint layout: ONE 294-slot head. Every category owns a fixed slice of the 294 slots
(garment_parse.category_keypoint_slice), so slot k always means the same landmark.
Kaleido TRAINING does not need this model (GT landmarks come from the csv); it is needed for
new wardrobe photos (inference).

Training layouts: official JSONs (finetune_keypoint_rcnn) or a single CSV with
path + b_box + category_id + a landmarks column (finetune_keypoint_rcnn_csv).
"""
import ast
import json
import os
from typing import Any, Dict, Optional

import numpy as np
from PIL import Image

try:
    from model.kaleido.garment_parse import (GarmentParse, category_name_from_id,
                                          category_keypoint_slice)
    from model.kaleido.df2_landmark_schema import (load_df2_items, item_landmarks,
                                                item_bbox_xyxy, item_category)
except ImportError:
    from garment_parse import (GarmentParse, category_name_from_id,
                               category_keypoint_slice)
    from df2_landmark_schema import (load_df2_items, item_landmarks,
                                     item_bbox_xyxy, item_category)

NUM_KEYPOINTS_ALL = 294
NUM_CLASSES = 14  # background + 13 garments


# 1. Keypoint R-CNN with 294 category-owned keypoint slots
def build_fashion_keypoint_rcnn(num_keypoints: int = NUM_KEYPOINTS_ALL,
                                num_classes: int = NUM_CLASSES,
                                pretrained: bool = True):
    from torchvision.models.detection import keypointrcnn_resnet50_fpn
    from torchvision.models.detection.keypoint_rcnn import KeypointRCNNPredictor
    from torchvision.models.detection.faster_rcnn import FastRCNNPredictor

    # load WITHOUT overriding num_classes / num_keypoints (torchvision forbids it with weights)
    model = keypointrcnn_resnet50_fpn(weights="DEFAULT" if pretrained else None,
                                      weights_backbone=None)
    in_ch = model.roi_heads.keypoint_predictor.kps_score_lowres.in_channels
    model.roi_heads.keypoint_predictor = KeypointRCNNPredictor(in_ch, num_keypoints)
    in_feat = model.roi_heads.box_predictor.cls_score.in_features
    model.roi_heads.box_predictor = FastRCNNPredictor(in_feat, num_classes)
    return model


class DF2KeypointRCNN:
    """Inference entry point. Main method: predict_parse(crop, category_id) -> GarmentParse."""

    def __init__(self, checkpoint: Optional[str] = None, device: Optional[str] = None,
                 score_thresh: float = 0.3,
                 vis_thresh: Optional[float] = 0.25, occ_thresh: Optional[float] = 0.05):
        """
        vis_thresh / occ_thresh: thresholds on 'keypoints_scores' (raw heatmap values, NOT probabilities)
        giving v=2 (visible) / v=1 (occluded) / v=0 (unreliable). Calibrate them on a validation split.
        If no confidence scores or no visibility threshold are supplied, landmarks are marked
        invalid (v=0), never automatically promoted to visible.
        """
        import torch
        self.checkpoint = checkpoint
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.score_thresh = score_thresh
        self.vis_thresh, self.occ_thresh = vis_thresh, occ_thresh
        self._model = None

    def _ensure_model(self):
        if self._model is not None:
            return
        import torch
        if not (self.checkpoint and os.path.exists(self.checkpoint)):
            raise FileNotFoundError(
                f"Keypoint checkpoint not found ({self.checkpoint}). Fine-tune one first with "
                "finetune_keypoint_rcnn(); COCO weights cannot predict garment landmarks.")
        model = build_fashion_keypoint_rcnn(pretrained=False)
        state = torch.load(self.checkpoint, map_location=self.device)
        model.load_state_dict(state.get("model", state))
        print(f"Loaded keypoint checkpoint: {self.checkpoint}")
        model.to(self.device).eval()
        self._model = model

    def predict(self, image: Image.Image) -> Dict[str, Any]:
        import torch
        import torchvision.transforms.functional as F
        self._ensure_model()
        img = image.convert("RGB")
        with torch.no_grad():
            res = self._model([F.to_tensor(img).to(self.device)])[0]
        keep = (res["scores"] >= self.score_thresh).cpu().numpy()
        kps_scores = res.get("keypoints_scores")
        return {
            "boxes": res["boxes"].cpu().numpy()[keep],
            "labels": res["labels"].cpu().numpy()[keep],
            "scores": res["scores"].cpu().numpy()[keep],
            "keypoints": res["keypoints"].cpu().numpy()[keep],                  # [N, 294, 3] (x, y, 1)
            "keypoints_scores": None if kps_scores is None else kps_scores.cpu().numpy()[keep],  # [N, 294]
            "image_size": img.size,
        }

    def _visibility(self, scores: Optional[np.ndarray], n: int) -> np.ndarray:
        if scores is None or self.vis_thresh is None:
            return np.zeros(n, dtype=np.float32)
        scores = np.asarray(scores, dtype=np.float32).reshape(-1)
        if len(scores) != n:
            return np.zeros(n, dtype=np.float32)
        v = np.zeros(n, dtype=np.float32)
        occ = self.occ_thresh if self.occ_thresh is not None else self.vis_thresh
        finite = np.isfinite(scores)
        v[finite & (scores >= occ)] = 1.0
        v[finite & (scores >= self.vis_thresh)] = 2.0
        return v

    def predict_parse(self, image: Image.Image, category_id: Optional[int] = None) -> GarmentParse:
        """Landmarks of ONE garment in the coordinate frame of `image` (the crop from cropper.py).

        category_id: 1..13, normally given by YOLO. The detection with the same label is preferred;
        when no detection has that label an empty parse is returned. The keypoint slice is always
        the one of `category_id`: landmarks predicted for another category are never reinterpreted.
        """
        pred = self.predict(image)
        boxes, labels, scores = pred["boxes"], pred["labels"], pred["scores"]
        if len(boxes) == 0:
            name = category_name_from_id(category_id) if category_id else "short sleeve top"
            return GarmentParse(category=name)
        order = np.argsort(-scores)
        if category_id is not None:
            cid = int(category_id)
            if not 1 <= cid <= 13:
                raise ValueError(f"category_id must be 1..13; got {category_id!r}")
            same = [i for i in order if int(labels[i]) == cid]
            # Never interpret landmarks predicted for another category as this category.
            if not same:
                return GarmentParse(category=category_name_from_id(cid))
            best = int(same[0])
        else:
            best = int(order[0])
            cid = int(labels[best])
        sl = category_keypoint_slice(cid)
        xy = np.asarray(pred["keypoints"][best][sl][:, :2], dtype=np.float32)
        ks = None if pred["keypoints_scores"] is None else pred["keypoints_scores"][best][sl]
        v = self._visibility(ks, len(xy))
        kp = np.concatenate([xy, v[:, None]], axis=1)
        return GarmentParse(category=category_name_from_id(cid), keypoints=kp, mask=None,
                            bbox=tuple(float(b) for b in boxes[best]))


DF2MatchRCNN = DF2KeypointRCNN  # old name kept so existing imports do not break


# 2. Fine-tune datasets + shared loop on DeepFashion2
class DF2FullImageDataset:
    """Torchvision-style dataset: full image + boxes / labels / 294-slot keypoints."""

    def __init__(self, json_dir: str, images_dir: str, limit: Optional[int] = None):
        self.json_dir, self.images_dir = json_dir, images_dir
        files = sorted(f for f in os.listdir(json_dir) if f.endswith(".json"))
        self.files = files[:limit] if limit else files

    def __len__(self):
        return len(self.files)

    def _image_path(self, stem: str) -> str:
        for e in (".jpg", ".jpeg", ".png"):
            p = os.path.join(self.images_dir, stem + e)
            if os.path.exists(p):
                return p
        return os.path.join(self.images_dir, stem + ".jpg")

    def __getitem__(self, idx: int, _depth: int = 0):
        import torch
        import torchvision.transforms.functional as F
        stem = os.path.splitext(self.files[idx])[0]
        items = load_df2_items(os.path.join(self.json_dir, self.files[idx]))
        boxes, labels, kps = [], [], []
        for it in items:
            box, cid = item_bbox_xyxy(it), item_category(it)
            if box is None or cid is None or not (1 <= cid <= 13):
                continue
            kp = np.zeros((NUM_KEYPOINTS_ALL, 3), dtype=np.float32)
            lm = item_landmarks(it)
            sl = category_keypoint_slice(cid)
            if lm is not None:
                n = min(len(lm), sl.stop - sl.start)
                kp[sl.start:sl.start + n] = np.asarray(lm[:n], dtype=np.float32)
            boxes.append(box); labels.append(cid); kps.append(kp)
        if not boxes:  # no usable garment: take another image instead of inventing a fake box
            if _depth > 20:
                raise RuntimeError("Too many consecutive annotation files without usable items.")
            return self.__getitem__((idx + 1) % len(self), _depth + 1)
        img = Image.open(self._image_path(stem)).convert("RGB")
        target = {
            "boxes": torch.as_tensor(np.asarray(boxes), dtype=torch.float32),
            "labels": torch.as_tensor(np.asarray(labels), dtype=torch.int64),
            "keypoints": torch.as_tensor(np.asarray(kps), dtype=torch.float32),
            "image_id": torch.tensor([idx]),
        }
        return F.to_tensor(img), target


class DF2CSVKeypointDataset:
    """One-row-per-garment CSV: path + b_box + category_id + a landmarks column."""

    BBOX_COLS = ("clean_bbox", "b_box", "xyxy", "bbox")

    def __init__(self, csv_path: str, images_dir: str = "", lm_col: str = "landmarks",
                 limit: Optional[int] = None):
        import pandas as pd
        df = pd.read_csv(csv_path, sep=None, engine="python")
        if limit:
            df = df.iloc[:limit]
        missing = {"path", "category_id"} - set(df.columns)
        if missing:
            raise ValueError(f"CSV {csv_path} misses columns: {sorted(missing)}")
        if lm_col not in df.columns:
            raise ValueError(f"CSV {csv_path} has no landmarks column {lm_col!r}; "
                             f"columns: {list(df.columns)}")
        self.rows = df.to_dict("records")
        if not self.rows:
            raise ValueError(f"CSV {csv_path} has no rows")
        self.images_dir = images_dir
        self.lm_col = lm_col

    def __len__(self):
        return len(self.rows)

    @staticmethod
    def _cell(cell):
        """CSV cell (JSON string / python literal / already a list) -> object."""
        if cell is None:
            return None
        if isinstance(cell, float) and cell != cell:  # NaN
            return None
        if isinstance(cell, str):
            text = cell.strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except (ValueError, TypeError):
                try:
                    return ast.literal_eval(text)
                except (ValueError, TypeError, SyntaxError):
                    return None
        if isinstance(cell, (list, tuple, np.ndarray)):
            return list(cell)
        return None

    def __getitem__(self, idx: int, _depth: int = 0):
        import torch
        import torchvision.transforms.functional as F
        row = self.rows[idx]
        box, cid, lm = None, None, None
        for col in self.BBOX_COLS:
            vals = self._cell(row.get(col))
            try:
                x1, y1, x2, y2 = [float(v) for v in vals[:4]]
                if x2 > x1 and y2 > y1:
                    box = [x1, y1, x2, y2]
                    break
            except (TypeError, ValueError):
                continue
        try:
            cid = int(row.get("category_id"))
        except (TypeError, ValueError):
            cid = None
        try:
            lm = np.asarray(self._cell(row.get(self.lm_col)), dtype=np.float32).reshape(-1, 3)
        except (ValueError, TypeError):
            lm = None
        if box is None or cid is None or not (1 <= cid <= 13) or lm is None or len(lm) == 0:
            if _depth > 50:  # unusable row: take the next one, never a fake box
                raise RuntimeError("Too many consecutive CSV rows without usable box/category/landmarks.")
            return self.__getitem__((idx + 1) % len(self), _depth + 1)
        raw_path = str(row.get("path", ""))
        img_path = raw_path if os.path.isabs(raw_path) else os.path.join(self.images_dir, raw_path)
        kp = np.zeros((NUM_KEYPOINTS_ALL, 3), dtype=np.float32)
        sl = category_keypoint_slice(cid)
        n = min(len(lm), sl.stop - sl.start)
        kp[sl.start:sl.start + n] = np.asarray(lm[:n], dtype=np.float32)
        with Image.open(img_path) as im:
            img = im.convert("RGB")
        target = {
            "boxes": torch.as_tensor(np.asarray([box]), dtype=torch.float32),
            "labels": torch.as_tensor(np.asarray([cid]), dtype=torch.int64),
            "keypoints": torch.as_tensor(kp[None], dtype=torch.float32),
            "image_id": torch.tensor([idx]),
        }
        return F.to_tensor(img), target


def _collate(batch):
    return tuple(zip(*batch))


def _run_finetune(model, loader, device, epochs, lr, save_path):
    """Shared SGD loop for the JSON and CSV datasets (saves every epoch)."""
    import torch
    model.to(device).train()
    optimizer = torch.optim.SGD([p for p in model.parameters() if p.requires_grad],
                                lr=lr, momentum=0.9, weight_decay=1e-4)
    for ep in range(epochs):
        running = 0.0
        for images, targets in loader:
            images = [im.to(device) for im in images]
            targets = [{k: v.to(device) for k, v in t.items()} for t in targets]
            loss = sum(model(images, targets).values())
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            running += loss.item()
        print(f"[KeypointRCNN] epoch {ep + 1}/{epochs} loss={running / max(len(loader), 1):.4f}")
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        torch.save({"model": model.state_dict()}, save_path)  # every epoch: Colab-safe
    print(f"Saved checkpoint: {save_path}")
    return save_path


def finetune_keypoint_rcnn(json_dir: str, images_dir: str,
                           save_path: str = "checkpoints/df2_keypoint_rcnn.pth",
                           epochs: int = 8, batch_size: int = 2, lr: float = 0.002,
                           limit: Optional[int] = None, device: Optional[str] = None):
    """Fine-tune the box / keypoint heads on DeepFashion2 (294 category-owned keypoint slots)."""
    import torch
    from torch.utils.data import DataLoader
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    loader = DataLoader(DF2FullImageDataset(json_dir, images_dir, limit),
                        batch_size=batch_size, shuffle=True, collate_fn=_collate)
    model = build_fashion_keypoint_rcnn(NUM_KEYPOINTS_ALL, NUM_CLASSES, pretrained=True)
    return _run_finetune(model, loader, device, epochs, lr, save_path)


def finetune_keypoint_rcnn_csv(csv_path: str, images_dir: str = "", lm_col: str = "landmarks",
                               save_path: str = "checkpoints/df2_keypoint_rcnn.pth",
                               epochs: int = 8, batch_size: int = 2, lr: float = 0.002,
                               limit: Optional[int] = None, device: Optional[str] = None):
    """Same fine-tune from a single CSV (path + b_box + category_id + landmarks column)."""
    import torch
    from torch.utils.data import DataLoader
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    loader = DataLoader(DF2CSVKeypointDataset(csv_path, images_dir, lm_col, limit),
                        batch_size=batch_size, shuffle=True, collate_fn=_collate)
    model = build_fashion_keypoint_rcnn(NUM_KEYPOINTS_ALL, NUM_CLASSES, pretrained=True)
    return _run_finetune(model, loader, device, epochs, lr, save_path)


if __name__ == "__main__":
    print("DF2KeypointRCNN ready (predict_parse / finetune_keypoint_rcnn[_csv]).")

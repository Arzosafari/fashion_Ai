import os
import sys
import ast
import json
import random
import pandas as pd
import numpy as np
from PIL import Image
from typing import Dict, Any, List, Optional
from collections import defaultdict


from model.vision.cropper import GarmentCropper


from model.kaleido.garment_parse import GarmentParse, category_name_from_id
from model.kaleido.df2_landmark_schema import check_landmark_array


def _present(value) -> bool:
    """True if a CSV cell holds a real (non-empty, non-NaN) value."""
    if value is None:
        return False
    if isinstance(value, float) and pd.isna(value):
        return False
    return bool(str(value).strip())


class KaleidoTrainingDataset:
    """Kaleido training data from an enriched CSV.

    Expected CSV flow:  captions csv (llm_description_agent.py)
                        -> precompute_landmarks.py --input_csv <captions csv>
                        -> enriched csv (this class), which therefore contains BOTH
                           fashion_caption and landmarks_orig_json / crop_box_used / mask_file.

    Each item gives the cropped garment plus a GarmentParse (landmarks and fabric mask in
    crop coordinates) that SemanticKPG consumes.

    Data hygiene (invalid rows are dropped LOUDLY in __init__, never patched silently):
      * category_id must be 1..13 (no clamping an invalid id into a valid class)
      * image paths must exist (missing_image="drop" drops, "error" raises)
      * a mask whose size differs from the crop is discarded with a warning: it means
        the crop box and the mask disagree, and resizing would hide that bug
    """

    def __init__(
        self,
        preprocessed_csv: str = "preprocessed_data/enriched_train.csv",
        images_base_dir: str = "",
        sample_size: Optional[int] = 20000,
        balance_categories: bool = True,
        is_training: bool = True,
        neg_sample_prob: float = 0.5,
        neg_same_cat_prob: float = 0.5,
        parse_dropout: float = 0.15,
        missing_image: str = "drop",
        random_state: int = 42
    ):
        self.images_base_dir = images_base_dir
        self.is_training = is_training
        self.neg_sample_prob = neg_sample_prob
        self.neg_same_cat_prob = neg_same_cat_prob
        # Train/inference robustness: with this prob the GT parse is dropped (train only),
        # so the model also sees fallback patches like inference sometimes does.
        self.parse_dropout = parse_dropout if is_training else 0.0
        self.cropper = GarmentCropper()
        self._mask_mismatch = 0
        self._lm_warned_cats = set()

        print(f"[Kaleido Dataset] Loading '{preprocessed_csv}'...")
        df = pd.read_csv(preprocessed_csv)
        print(f"  Total rows: {len(df)}")
        if not ({"fashion_caption", "fashion_description"} & set(df.columns)):
            print("  WARNING: no caption column - text will be a dummy sentence and ITM becomes trivial. "
                  "Run llm_description_agent.py first, then precompute_landmarks.py on its output.")

        df = self._drop_bad_categories(df)
        df = self._drop_missing_images(df, missing_image)

        if sample_size and sample_size < len(df):
            if balance_categories and "category_id" in df.columns:
                num_classes = df["category_id"].nunique()
                per_class = sample_size // num_classes
                print(f"  Balanced subset: ~{per_class} rows x {num_classes} classes")
                sampled_groups = []
                for cid, grp in df.groupby("category_id"):
                    n = min(len(grp), per_class)
                    sampled_groups.append(grp.sample(n=n, random_state=random_state))
                df = pd.concat(sampled_groups).sample(
                    frac=1.0, random_state=random_state).reset_index(drop=True)
            else:
                print(f"  Random subset: {sample_size} rows...")
                df = df.sample(n=sample_size, random_state=random_state).reset_index(drop=True)

        self.records = df.to_dict("records")
        # category -> row positions (for hard ITM negatives: same category, another item)
        self._cat_positions: Dict[int, List[int]] = defaultdict(list)
        for i, r in enumerate(self.records):
            try:
                self._cat_positions[int(r.get("category_id"))].append(i)
            except (TypeError, ValueError):
                continue
        print(f"  Active samples: {len(self.records)}")

    # hygiene
    @staticmethod
    def _drop_bad_categories(df: pd.DataFrame) -> pd.DataFrame:
        if "category_id" not in df.columns:
            raise ValueError("CSV has no category_id column.")
        cids = pd.to_numeric(df["category_id"], errors="coerce")
        ok = cids.between(1, 13)
        n_bad = int((~ok).sum())
        if n_bad:
            print(f"  Dropped {n_bad} rows with category_id outside 1..13 (never clamped).")
        return df[ok].reset_index(drop=True)

    def _resolve_path(self, raw_path: str) -> str:
        if self.images_base_dir and not os.path.isabs(raw_path):
            return os.path.join(self.images_base_dir, raw_path)
        return raw_path

    def _drop_missing_images(self, df: pd.DataFrame, mode: str) -> pd.DataFrame:
        if mode not in ("drop", "error"):
            raise ValueError(f"missing_image must be 'drop' or 'error', got {mode!r}")
        paths = [self._resolve_path(str(p)) for p in df.get("path", [])]
        missing = [p for p in paths if not p or not os.path.exists(p)]
        if missing:
            if mode == "error":
                raise FileNotFoundError(f"{len(missing)} image paths do not exist, e.g. {missing[0]!r}")
            print(f"  Dropped {len(missing)} rows with missing images (e.g. {missing[0]!r}).")
            keep = [bool(p) and os.path.exists(p) for p in paths]
            return df[keep].reset_index(drop=True)
        return df

    def __len__(self) -> int:
        return len(self.records)


    @staticmethod
    def _category_name(row: Dict[str, Any]) -> str:
        try:
            return category_name_from_id(int(row.get("category_id")))
        except (TypeError, ValueError, IndexError):
            return str(row.get("category_name", "clothing"))

    def _caption_of(self, row: Dict[str, Any]) -> str:
        for col in ("fashion_caption", "fashion_description"):
            if col in row and _present(row[col]):
                return str(row[col])
        return f"A {self._category_name(row)} in modern style."

    def _sample_negative_caption(self, my_idx: int, category_id: int) -> Optional[str]:
        """Real caption of ANOTHER item: same category (hard) or a different one.

        Different-category negatives are too easy (the model only learns "trousers vs
        dress"); same-category negatives force it to learn color / material / pattern.
        """
        same = [i for i in self._cat_positions.get(int(category_id), []) if i != my_idx]
        if same and random.random() < self.neg_same_cat_prob:
            return self._caption_of(self.records[random.choice(same)])
        for _ in range(10):
            r = self.records[random.randrange(len(self.records))]
            try:
                if int(r.get("category_id", -1)) != int(category_id):
                    return self._caption_of(r)
            except (TypeError, ValueError):
                continue
        return None


    def __getitem__(self, idx: int) -> Dict[str, Any]:
        row = self.records[idx]

        # 1. Load the full image (validated in __init__; a runtime miss is a loud error)
        img_path = self._resolve_path(str(row.get("path", "")))
        if not os.path.exists(img_path):
            raise FileNotFoundError(f"row {idx}: image not found: {img_path!r}")
        full_img = Image.open(img_path).convert("RGB")

        # 2. Crop the garment (Kaleido input). Enriched rows reuse the exact precompute box so that
        # landmarks / mask stay aligned; otherwise a 5% margin crop.
        crop_box = row.get("crop_box_used", None)
        if _present(crop_box):
            cb = json.loads(crop_box) if isinstance(crop_box, str) else list(crop_box)
            ox, oy = int(cb[0]), int(cb[1])
            cropped_img = full_img.crop((ox, oy, int(cb[2]), int(cb[3])))
        else:
            clean_bbox = row.get("clean_bbox", row.get("b_box"))
            if isinstance(clean_bbox, str):
                clean_bbox = ast.literal_eval(clean_bbox)
            cropped_img, (ox, oy) = self.cropper.crop_region_with_origin(
                full_img, [int(v) for v in clean_bbox], padding_pct=0.05)
        cw, ch = cropped_img.size

        # 2b. GT landmarks (shifted into crop coordinates, NOT clipped) + fabric mask
        landmarks_crop, mask_crop = None, None
        raw_lm = row.get("landmarks_orig_json", None)
        if _present(raw_lm):
            try:
                lm = np.asarray(json.loads(raw_lm), dtype=np.float32).reshape(-1, 3)
                lm[:, 0] -= ox
                lm[:, 1] -= oy
                ok, reason = check_landmark_array(row.get("category_id"), lm)
                if reason and "WARNING" in reason:
                    cid = row.get("category_id")
                    if cid not in self._lm_warned_cats:  # warn once per category
                        print(f"  [row {idx}] {reason}")
                        self._lm_warned_cats.add(cid)
                landmarks_crop = lm if ok else None
            except (ValueError, TypeError):
                landmarks_crop = None
        raw_mask = row.get("mask_file", None)
        if _present(raw_mask) and os.path.exists(str(raw_mask)):
            try:
                m = np.asarray(Image.open(str(raw_mask)).convert("L")) > 127
                if m.shape != (ch, cw):
                    # Strict: a misaligned mask means crop and mask disagree; resizing
                    # would hide that bug, so the mask is discarded instead.
                    self._mask_mismatch += 1
                    if self._mask_mismatch <= 3:
                        print(f"  [row {idx}] WARNING: mask {m.shape} != crop {(ch, cw)}; "
                              f"mask discarded.")
                    mask_crop = None
                else:
                    mask_crop = m.astype(bool)
            except (OSError, ValueError):
                mask_crop = None

        # 3. Category labels (invalid ids were dropped in __init__; never clamp here)
        raw_cid = int(row.get("category_id"))
        if not 1 <= raw_cid <= 13:
            raise ValueError(f"row {idx}: category_id {raw_cid} outside 1..13")
        category_target = raw_cid - 1
        cat_name = self._category_name(row)
        if self.parse_dropout > 0 and random.random() < self.parse_dropout:
            parse = None  # train/inference mix: model must survive fallback patches
        else:
            parse = GarmentParse(category=cat_name, keypoints=landmarks_crop, mask=mask_crop)

        # 4. Fashion text + ITM negative sampling
        desc_text = self._caption_of(row)
        itm_target = 1
        if self.is_training and random.random() < self.neg_sample_prob:
            neg = self._sample_negative_caption(idx, raw_cid)
            if neg is not None:
                desc_text, itm_target = neg, 0

        llm_metadata = {
            "category": cat_name,
            "material": "[MASK]",
            "pattern": "[MASK]",
            "style": "[MASK]",
            "color": "[MASK]",
            "description": desc_text
        }

        return {
            "image": cropped_img,
            "category": cat_name,          # DeepFashion2 name (used only if parse is None)
            "category_id": raw_cid,
            "parse": parse,                # GarmentParse in crop coordinates (or None by dropout)
            "llm_metadata": llm_metadata,
            "free_text": desc_text,
            "category_target": category_target,
            "itm_target": itm_target
        }


def kaleido_collate_fn(batch: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Custom collate: images/parses stay lists, targets are tensors."""
    import torch
    return {
        "image": [b["image"] for b in batch],
        "category": [b["category"] for b in batch],
        "category_id": [b.get("category_id") for b in batch],
        "parse": [b.get("parse") for b in batch],
        "llm_metadata": [b["llm_metadata"] for b in batch],
        "free_text": [b["free_text"] for b in batch],
        "category_target": torch.tensor([b["category_target"] for b in batch],
                                        dtype=torch.long),
        "itm_target": torch.tensor([b["itm_target"] for b in batch], dtype=torch.long),
    }


if __name__ == "__main__":
    print("KaleidoTrainingDataset ready.")

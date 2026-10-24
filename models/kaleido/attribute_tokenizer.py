"""Tokenizer for image-grounded garment descriptions.

Only visual garment attributes are serialized here. Style, season, occasion,
destination, weather and user preferences belong to the separate contextual
recommendation layer and must not leak into the garment's semantic text input.

Important: inserting [MASK] tokens does not by itself create an MLM training
objective. The training code must construct appropriate MLM labels/losses.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

import torch
from transformers import BertTokenizer


class FashionAttributeTokenizer:
    """Build BERT inputs from visual attributes plus an image-grounded caption.

    Accepted visual metadata keys:
        - color
        - pattern
        - material (only when reliably known from annotation/metadata)

    Keys such as style, season, occasion, destination and weather are
    deliberately ignored so they cannot enter the visual garment embedding
    through this tokenizer.
    """

    SPECIAL_TOKENS = ["[MAT]", "[PAT]", "[COL]"]
    VISUAL_KEYS = ("material", "pattern", "color")
    UNKNOWN_VALUES = {
        "", "unknown", "unk", "none", "null", "n/a", "na", "unsure",
        "uncertain", "unclear", "not sure", "not known", "not identifiable",
        "not determined", "unspecified",
    }

    def __init__(
        self,
        base_tokenizer_name: str = "bert-base-uncased",
        max_len: int = 48,
    ) -> None:
        if not isinstance(max_len, int) or max_len < 8:
            raise ValueError("max_len must be an integer >= 8")
        self.max_len = max_len
        self.tokenizer = BertTokenizer.from_pretrained(base_tokenizer_name)
        self.tokenizer.add_special_tokens(
            {"additional_special_tokens": self.SPECIAL_TOKENS}
        )

    @property
    def vocab_size(self) -> int:
        """Tokenizer vocabulary size including added markers; model must match it."""
        return len(self.tokenizer)

    @classmethod
    def _clean_value(cls, value: Any, mask_token: str) -> str:
        if value is None:
            return mask_token
        # Lists/dicts are almost always malformed metadata for a single slot.
        if isinstance(value, (dict, list, tuple, set)):
            return mask_token
        text = re.sub(r"\s+", " ", str(value)).strip()
        if text.casefold() in cls.UNKNOWN_VALUES:
            return mask_token
        return text

    def format_prompt(self, visual_meta: Dict[str, Any], caption: str = "") -> str:
        """Serialize visible garment attributes and the caption, not context.

        Any supplied keys other than material/pattern/color are ignored.
        `caption` should be generated from the image and should not contain
        inferred season, occasion, destination or user-preference claims.
        """
        if not isinstance(visual_meta, dict):
            raise TypeError(
                f"visual_meta must be a dict, got {type(visual_meta).__name__}"
            )
        if caption is None:
            caption = ""
        if not isinstance(caption, str):
            raise TypeError(f"caption must be str, got {type(caption).__name__}")

        mask = self.tokenizer.mask_token
        mat = self._clean_value(visual_meta.get("material"), mask)
        pat = self._clean_value(visual_meta.get("pattern"), mask)
        col = self._clean_value(visual_meta.get("color"), mask)

        parts = [f"[MAT] {mat}", f"[PAT] {pat}", f"[COL] {col}"]
        clean_caption = re.sub(r"\s+", " ", caption).strip()
        if clean_caption:
            parts.append(clean_caption)
        return " ".join(parts)

    def encode(
        self,
        visual_meta: Dict[str, Any],
        caption: str = "",
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """Return input_ids and attention_mask, each with shape (1, max_len)."""
        formatted_text = self.format_prompt(visual_meta, caption)
        encoded = self.tokenizer(
            formatted_text,
            padding="max_length",
            max_length=self.max_len,
            truncation=True,
            return_tensors="pt",
        )
        return encoded["input_ids"], encoded["attention_mask"]


# Canonical name used by the model and tests.
AttributeTokenizer = FashionAttributeTokenizer


if __name__ == "__main__":
    tokenizer = AttributeTokenizer()
    sample_meta = {
        "material": None,  # unknown composition remains [MASK]
        "pattern": "solid",
        "color": "charcoal grey",
        # These are intentionally ignored by the visual tokenizer:
        "style": "minimalist formal",
        "season": "autumn and winter",
        "occasion": "business conference",
        "destination": "office",
    }
    caption = (
        "A charcoal grey sleeveless dress with narrow shoulder straps and a long, "
        "gently flared skirt. The fabric composition is unclear."
    )
    formatted = tokenizer.format_prompt(sample_meta, caption)
    assert "[STY]" not in formatted and "[SEA]" not in formatted and "[OCC]" not in formatted
    assert "business conference" not in formatted and "office" not in formatted
    input_ids, attn_mask = tokenizer.encode(sample_meta, caption)
    print("FashionAttributeTokenizer OK")
    print("  formatted:", formatted)
    print("  input_ids shape:", tuple(input_ids.shape))
    print("  attention_mask shape:", tuple(attn_mask.shape))
    print("  vocab_size:", tokenizer.vocab_size)

import torch
import torch.nn as nn
from typing import Dict


class SelfSupervisedHeads(nn.Module):
    """The 3 training heads of Semantic-KaleidoBERT (training only).

    There is no season head: captions never name a season, so no supervision
    exists for one. Season suitability is decided at recommendation time from
    weather/destination context plus garment metadata (VLM seasons / LLM).
    """
    def __init__(
        self,
        hidden_dim: int = 768,
        vocab_size: int = 30525,   # always pass len(tokenizer); the default is bert-base + 3 markers
        num_categories: int = 13,  # 13 DeepFashion2 categories
    ):
        super().__init__()

        # 1. Image-Text Matching head
        self.itm_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Linear(hidden_dim // 2, 2)  # 0 = mismatch, 1 = match
        )

        # 2. Masked Language Modeling head
        self.mlm_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, vocab_size)
        )

        # 3. DeepFashion2 category head
        self.category_head = nn.Linear(hidden_dim, num_categories)

    def forward(
        self,
        cls_embedding: torch.Tensor,     # [batch_size, 768]
        hidden_states: torch.Tensor,     # [batch_size, seq_len, 768]
        text_len: int = 48,
    ) -> Dict[str, torch.Tensor]:
        """Compute task logits for the loss."""
        # 1. ITM from [CLS]
        itm_logits = self.itm_head(cls_embedding)  # [batch_size, 2]

        # 2. MLM over the text part
        text_hidden = hidden_states[:, :text_len, :]  # [batch_size, text_len, 768]
        mlm_logits = self.mlm_head(text_hidden)       # [batch_size, text_len, vocab_size]

        # 3. Category from [CLS] (the category NAME is masked in the input text)
        category_logits = self.category_head(cls_embedding)  # [batch_size, 13]

        return {
            "itm_logits": itm_logits,
            "mlm_logits": mlm_logits,
            "category_logits": category_logits
        }


if __name__ == "__main__":
    heads = SelfSupervisedHeads(hidden_dim=768)
    dummy_cls = torch.randn(2, 768)
    dummy_states = torch.randn(2, 57, 768)

    outputs = heads(dummy_cls, dummy_states, text_len=48)
    print("Self-supervised heads OK!")
    for k, v in outputs.items():
        print(f"  {k}: {tuple(v.shape)}")

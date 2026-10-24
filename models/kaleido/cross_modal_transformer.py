import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import Optional, Tuple

class CrossModalTransformer(nn.Module):
    """
    Multimodal Transformer Fusing Visual Patch Features and LLM Text Tokens (Step 4)
    Extracting Unified [CLS] Vector for Digital Wardrobe and Outfit Scoring
    """
    def __init__(
        self,
        hidden_dim: int = 768,
        num_layers: int = 6,
        num_heads: int = 8,
        vocab_size: int = 30528, 
        max_seq_len: int = 128,
        num_patch_roles: int = 9
    ):
        super().__init__()
        self.hidden_dim = hidden_dim
        self.max_seq_len = int(max_seq_len)
        if self.max_seq_len < 2:
            raise ValueError("max_seq_len must be >= 2")

        self.word_embeddings = nn.Embedding(vocab_size, hidden_dim)
        
        self.modality_embeddings = nn.Embedding(2, hidden_dim)
        
        self.position_embeddings = nn.Embedding(max_seq_len, hidden_dim)

        # patch role: global, upper_boundary, torso, side, hem, 4 x texture
        self.patch_role_embeddings = nn.Embedding(num_patch_roles, hidden_dim)

        self.layer_norm = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(0.1)

        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=num_heads,
            dim_feedforward=hidden_dim * 4,
            dropout=0.1,
            activation="gelu",
            batch_first=True
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers, enable_nested_tensor=False)

    def forward(
        self,
        input_ids: torch.Tensor,              # [batch_size, text_len]
        patch_embeddings: torch.Tensor,       # [batch_size, num_patches, hidden_dim]
        patch_valid: Optional[torch.Tensor] = None,  # [batch_size, num_patches] bool, False = ignore this patch
        text_valid: Optional[torch.Tensor] = None    # [batch_size, text_len] bool/0-1, tokenizer attention_mask (0 = [PAD])
    ) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Input: Text tokens and embeddings of 9 visual patches
        Output:
            cls_embedding: 768-dimensional dense [CLS] vector
            all_hidden_states: All hidden states for Step 5 task heads
        """
        batch_size = input_ids.shape[0]
        text_len = input_ids.shape[1]
        num_patches = patch_embeddings.shape[1]
        seq_len = text_len + num_patches
        if seq_len > self.max_seq_len:
            raise ValueError(f"fused sequence length {seq_len} exceeds max_seq_len={self.max_seq_len}")
        if patch_embeddings.shape[-1] != self.hidden_dim:
            raise ValueError(f"patch embedding dimension must be {self.hidden_dim}, got {patch_embeddings.shape[-1]}")
        if input_ids.numel() and (int(input_ids.min()) < 0 or int(input_ids.max()) >= self.word_embeddings.num_embeddings):
            raise ValueError("input_ids contain token ids outside the configured tokenizer vocabulary")

        text_emb = self.word_embeddings(input_ids) # [batch_size, text_len, hidden_dim]

        role_ids = torch.arange(num_patches, device=input_ids.device).unsqueeze(0).expand(batch_size, -1)
        patch_embeddings = patch_embeddings + self.patch_role_embeddings(role_ids)

        fused_seq = torch.cat([text_emb, patch_embeddings], dim=1)

        seg_ids = torch.cat([
            torch.zeros((batch_size, text_len), dtype=torch.long, device=input_ids.device),
            torch.ones((batch_size, num_patches), dtype=torch.long, device=input_ids.device)
        ], dim=1)
        modality_emb = self.modality_embeddings(seg_ids)

        positions = torch.arange(seq_len, dtype=torch.long, device=input_ids.device).unsqueeze(0).expand(batch_size, -1)
        pos_emb = self.position_embeddings(positions)

        x = self.layer_norm(fused_seq + modality_emb + pos_emb)
        x = self.dropout(x)

        pad_mask = None  # True = position is ignored by attention ([PAD] tokens and invalid patches)
        if patch_valid is not None or text_valid is not None:
            text_ok = (torch.ones((batch_size, text_len), dtype=torch.bool, device=input_ids.device)
                       if text_valid is None else text_valid.to(device=input_ids.device, dtype=torch.bool))
            patch_ok = (torch.ones((batch_size, num_patches), dtype=torch.bool, device=input_ids.device)
                        if patch_valid is None else patch_valid.to(device=input_ids.device, dtype=torch.bool))
            pad_mask = ~torch.cat([text_ok, patch_ok], dim=1)

        hidden_states = self.transformer(x, src_key_padding_mask=pad_mask) # [batch_size, seq_len, hidden_dim]

        cls_token = hidden_states[:, 0, :]
        cls_normalized = F.normalize(cls_token, p=2, dim=-1)

        return cls_normalized, hidden_states

    @torch.no_grad()
    def init_text_embeddings_from_bert(self, hf_name: str = "bert-base-uncased") -> bool:
        """Copy BERT word vectors into the text embedding table (shared ids only).

        Training a word embedding from scratch on 20k captions cannot rival BERT's.
        Added marker ids keep their random init. Returns False (with a warning) when
        the weights cannot be downloaded, e.g. on an offline machine.
        """
        try:
            from transformers import BertModel
            bert = BertModel.from_pretrained(hf_name)
            src = bert.embeddings.word_embeddings.weight.detach().cpu()
        except Exception as e:  # offline / no transformers: keep random init
            print(f"[CrossModal] WARNING: BERT init skipped ({e}). Text embeddings stay random.")
            return False
        n = min(src.shape[0], self.word_embeddings.num_embeddings)
        self.word_embeddings.weight[:n].copy_(src[:n].to(self.word_embeddings.weight.device))
        print(f"[CrossModal] text embeddings initialized from {hf_name} ({n} shared ids).")
        return True

if __name__ == "__main__":
    model = CrossModalTransformer(hidden_dim=768, num_layers=4, num_heads=8)
    dummy_text_ids = torch.randint(0, 1000, (2, 48))
    dummy_patches = torch.randn(2, 9, 768)
    
    valid = torch.ones(2, 9, dtype=torch.bool)
    valid[1, 3] = False  # e.g. a sleeveless garment has no sleeve patch
    cls_vec, all_states = model(dummy_text_ids, dummy_patches, valid)
    print("Step 4 (Cross-Modality Transformer) executed successfully!")
    print(f"Final [CLS] vector shape: {cls_vec.shape} ([batch, 768])")
    print(f"Full sequence hidden states shape: {all_states.shape} ([batch, 57, 768])")

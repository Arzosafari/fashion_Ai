# semantic_kaleido_model.py
"""
SemanticKaleidoBERT: the full model. One garment crop + its metadata + free text ->
cross-modal transformer -> one embedding per garment + self-supervised heads.

Text is a SINGLE stream (structured attributes + free text, length 48); vision is
9 patch embeddings with spatial coords fused in the backbone. Patch roles are added
in the transformer. The pooled vector is the first text position ([MAT] marker).

Self-supervision: ITM (does this text belong to this garment?), category, MLM over
attribute words. Visual masking is intentionally skipped (weak evidence).
"""
import numpy as np
from PIL import Image
from typing import List, Dict, Any, Optional


from model.kaleido.semantic_kpg import SemanticKPG
from model.kaleido.visual_backbone import SwinVisualBackbone
from model.kaleido.attribute_tokenizer import AttributeTokenizer
from model.kaleido.cross_modal_transformer import CrossModalTransformer
from model.kaleido.self_supervised_heads import SelfSupervisedHeads
from model.kaleido.text_masking import AttributeTextMasker
from model.kaleido.garment_parse import GarmentParse


class SemanticKaleidoBERT:
    def __init__(
        self,
        hidden_dim: int = 768,
        num_layers: int = 4,
        num_heads: int = 8,
        hide_category_text: bool = True,
        hide_season_text: bool = True,
        backbone_pretrained: bool = True,
        init_text_from_bert: bool = True,
    ):
        # Category names are masked in the text (train AND inference): without this the
        # ITM/category heads learn "the text says dress" and ignore the image.
        self.hide_category_text = hide_category_text
        # Season words are masked in the text (train AND inference): captions must
        # never name a season, and this guard drops any that slip through.
        self.hide_season_text = hide_season_text
        self.kpg = SemanticKPG()
        self.tokenizer = AttributeTokenizer()
        self.visual_backbone = SwinVisualBackbone(hidden_dim=hidden_dim,
                                                  pretrained=backbone_pretrained)
        self.transformer = CrossModalTransformer(
            hidden_dim=hidden_dim, num_layers=num_layers, num_heads=num_heads,
            vocab_size=self.tokenizer.vocab_size)  # dynamic: follows the real tokenizer
        if init_text_from_bert:
            self.transformer.init_text_embeddings_from_bert("bert-base-uncased")
        self.heads = SelfSupervisedHeads(hidden_dim=hidden_dim,
                                         vocab_size=self.tokenizer.vocab_size)
        self.masker = AttributeTextMasker(self.tokenizer.tokenizer)


    def _encode_images(self, images: List[Image.Image], categories: List[str],
                       parses: Optional[List[Optional[GarmentParse]]] = None):
        import torch
        dev = next(self.visual_backbone.parameters()).device
        embs, valids = [], []
        for i, img in enumerate(images):
            parse = parses[i] if parses is not None else None
            cat = parse.category if parse is not None else categories[i]
            tensors, coords, valid = self.kpg(img, parse=parse, category=cat)
            with torch.set_grad_enabled(self.transformer.training):
                embs.append(self.visual_backbone(tensors.to(dev), coords.to(dev)))
            valids.append(valid)
        return torch.stack(embs), torch.stack(valids)  # [B, 9, H], [B, 9]

    def _encode_texts(self, llm_metadata: List[Dict[str, Any]], free_texts: List[str]):
        import torch
        ids, masks = [], []
        for meta, txt in zip(llm_metadata, free_texts):
            i, m = self.tokenizer.encode(meta, txt)
            ids.append(i)
            masks.append(m)
        text_ids, text_mask = torch.cat(ids, dim=0), torch.cat(masks, dim=0)
        if self.hide_category_text:
            text_ids = torch.from_numpy(self.masker.hide_category(
                text_ids.numpy(), text_mask.numpy())).to(text_ids.device)
        if self.hide_season_text:
            text_ids = torch.from_numpy(self.masker.hide_season(
                text_ids.numpy(), text_mask.numpy())).to(text_ids.device)
        # training / inference may run on GPU: text must follow the modules
        dev = next(self.transformer.parameters()).device
        return text_ids.to(dev), text_mask.to(dev)  # [B, 48]


    def extract_embedding(self, image: Image.Image, llm_metadata: Dict[str, Any],
                          free_text: str = "", category: str = "top",
                          parse: Optional[GarmentParse] = None):
        """Inference: one L2-normalized embedding per garment (no MLM corruption)."""
        import torch
        was_training = self.transformer.training
        self.transformer.eval()
        with torch.no_grad():
            patch_emb, patch_valid = self._encode_images([image], [category], [parse])
            text_ids, text_mask = self._encode_texts([llm_metadata], [free_text])
            cls, _ = self.transformer(text_ids, patch_emb, patch_valid, text_mask)
        if was_training:
            self.transformer.train()
        return cls

    def __call__(self, *args, **kwargs):
        return self.forward(*args, **kwargs)

    def forward(self, images: List[Image.Image], categories: List[str],
                llm_metadata: List[Dict[str, Any]], free_texts: List[str],
                parses: Optional[List[Optional[GarmentParse]]] = None,
                mlm_allowed=None):
        """Training forward: embeddings + all head logits (+ MLM labels).

        mlm_allowed: optional bool mask [B]; MLM corrupts only matched pairs
        (a swapped caption must not teach the text encoder either).
        """
        import torch
        patch_emb, patch_valid = self._encode_images(images, categories, parses)
        text_ids, text_mask = self._encode_texts(llm_metadata, free_texts)

        text_ids_in, mlm_labels = text_ids, None
        if self.transformer.training and mlm_allowed is not False:
            # Masking is numpy: move to CPU first (text already follows the GPU).
            ids_cpu, mask_cpu = text_ids.cpu().numpy(), text_mask.cpu().numpy()
            masked, labels = self.masker.mask_attribute_words(ids_cpu, mask_cpu)
            if mlm_allowed is not None:
                allow = np.asarray(mlm_allowed).astype(bool)
                masked[~allow] = ids_cpu[~allow]
                labels[~allow] = -100
            text_ids_in = torch.from_numpy(masked).to(text_ids.device)
            mlm_labels = torch.from_numpy(labels).to(text_ids.device)

        dev = text_ids_in.device
        cls, states = self.transformer(text_ids_in, patch_emb.to(dev),
                                       patch_valid.to(dev), text_mask.to(dev))
        logits = self.heads(cls, states, text_len=text_ids_in.shape[1])
        return {
            "embedding": cls,
            "itm_logits": logits["itm_logits"],
            "category_logits": logits["category_logits"],
            "mlm_logits": logits["mlm_logits"],
            "mlm_labels": mlm_labels,
            "patch_valid": patch_valid,
        }


    def train(self):
        self.transformer.train()

    def eval(self):
        self.transformer.eval()

    def to(self, device):
        self.transformer.to(device)
        self.heads.to(device)
        self.visual_backbone.to(device)
        return self

    def load_checkpoint(self, path: str, device=None):
        """Load a checkpoint saved by train_kaleido.py (transformer/heads/backbone).

        Tolerant to older checkpoints: saved tensors whose name or shape no
        longer exists (e.g. the removed season head, the 6-marker MLM layer)
        are skipped with a note instead of raising.
        """
        import torch
        device = device or next(self.transformer.parameters()).device
        blob = torch.load(path, map_location=device)
        for name, module in (("transformer", self.transformer),
                             ("heads", self.heads),
                             ("backbone", self.visual_backbone)):
            if name not in blob:
                print(f"[Kaleido] {name}: not in checkpoint, skipped.")
                continue
            ours = module.state_dict()
            saved = blob[name]
            kept = {k: v for k, v in saved.items()
                    if k in ours and tuple(ours[k].shape) == tuple(v.shape)}
            skipped = [k for k in saved if k not in kept]
            module.load_state_dict(kept, strict=False)
            print(f"[Kaleido] {name}: loaded {len(kept)} tensors"
                  + (f", skipped {skipped}." if skipped else "."))
        print(f"[Kaleido] loaded checkpoint: {path}")
        return self.to(device)

    def parameters(self):
        import itertools
        return itertools.chain(self.transformer.parameters(), self.heads.parameters(),
                               self.visual_backbone.parameters())



if __name__ == "__main__":
    print("SemanticKaleidoBERT demo...", flush=True)
    model = SemanticKaleidoBERT(hidden_dim=768, num_layers=1, num_heads=4,
                                backbone_pretrained=False, init_text_from_bert=False)

    rng = np.random.RandomState(0)
    demo_img = Image.fromarray((rng.rand(300, 250, 3) * 255).astype(np.uint8))
    test_meta = {"material": "cotton", "pattern": "solid", "style": "casual",
                 "color": "navy"}
    # a slice of real GT landmarks (cat-1 has 25): the count is what matters here
    kp = np.zeros((25, 3), dtype=np.float32)
    kp[:, 0] = np.linspace(40, 210, 25)
    kp[:, 1] = np.linspace(30, 270, 25)
    kp[:, 2] = 2
    demo_mask = np.zeros((300, 250), bool)
    demo_mask[20:280, 30:220] = True
    demo_parse = GarmentParse(category="short sleeve top", keypoints=kp, mask=demo_mask)

    emb = model.extract_embedding(demo_img, test_meta,
                                  free_text="Navy cotton top in casual style.",
                                  category="short sleeve top", parse=demo_parse)
    print(f"embedding: {tuple(emb.shape)}")

    import torch
    model.train()
    with torch.inference_mode():  # shape demo only: no autograd graph (OOM-safe on CPU)
        out = model.forward([demo_img], ["short sleeve top"], [test_meta],
                            ["Navy cotton top in casual style."], parses=[demo_parse])
    print(f"itm: {tuple(out['itm_logits'].shape)}, cat: {tuple(out['category_logits'].shape)}, "
          f"mlm: {tuple(out['mlm_logits'].shape)}", flush=True)

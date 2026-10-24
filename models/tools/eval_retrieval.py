#!/usr/bin/env python3
"""
Stage-6 evaluation for a trained SemanticKaleidoBERT checkpoint.

Loads checkpoints/kaleido_v2.pth ({transformer, heads, backbone}) and reports,
on an enriched validation CSV:
  P@1/P@5/P@10 : same-category precision among top-K image neighbours.
                 All items share one NEUTRAL text, so CLS differences are purely visual.
  ITM accuracy : matched pairs score 1, swapped-caption pairs score 0.
  category / season accuracy on matched pairs (season ignores -100 rows).

Needs: torch, transformers (BERT vocab), an enriched CSV (precompute_landmarks.py).
Slow on CPU (one Swin pass per patch per item); prefer --device cuda.

Example:
    python3 eval_retrieval.py --val_csv preprocessed_data/enriched_val.csv \\
        --ckpt checkpoints/kaleido_v2.pth --n 260
"""
import argparse
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model.kaleido.semantic_kaleido_model import SemanticKaleidoBERT
from model.tools.kaleido_training_dataset import KaleidoTrainingDataset


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--val_csv", required=True)
    ap.add_argument("--images_dir", default="")
    ap.add_argument("--ckpt", default="checkpoints/kaleido_v2.pth")
    ap.add_argument("--n", type=int, default=260, help="balanced subset size (13 cats)")
    ap.add_argument("--batch_size", type=int, default=4)
    ap.add_argument("--num_layers", type=int, default=4, help="must match training")
    ap.add_argument("--num_heads", type=int, default=8, help="must match training")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--topk", default="1,5,10")
    a = ap.parse_args()

    ds = KaleidoTrainingDataset(preprocessed_csv=a.val_csv, images_base_dir=a.images_dir,
                                sample_size=a.n, is_training=False)
    items = [ds[i] for i in range(len(ds))]
    print(f"[eval] items: {len(items)}")
    if not items:
        raise ValueError("validation subset is empty")

    model = SemanticKaleidoBERT(hidden_dim=768, num_layers=a.num_layers,
                                num_heads=a.num_heads, backbone_pretrained=False,
                                init_text_from_bert=False)
    model.load_checkpoint(a.ckpt, a.device)
    model.eval()

    # --- 1. visual embeddings with neutral text ---
    embs = [model.extract_embedding(it["image"], llm_metadata={}, free_text="",
                                    category=it["category"], parse=it["parse"]
                                    ).detach().cpu().numpy().reshape(-1)
            for it in items]
    embs = np.stack(embs)
    embs /= np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9
    cats = np.array([it["category_id"] for it in items])
    sims = embs @ embs.T
    np.fill_diagonal(sims, -1.0)  # a query never retrieves itself
    order = np.argsort(-sims, axis=1)
    for k in [int(x) for x in a.topk.split(",")]:
        hits = [(cats[order[i, :k]] == cats[i]).mean() for i in range(len(items))]
        print(f"[eval] P@{k} (same category): {np.mean(hits):.3f}")

    # --- 2. ITM / category / season on matched + swapped pairs ---
    cat_t = np.array([it["category_target"] for it in items])
    sea_t = np.array([it["season_target"] for it in items])
    texts = [it["free_text"] for it in items]
    swapped = texts[1:] + texts[:1]
    itm_ok = itm_n = cat_ok = sea_ok = sea_n = 0
    with torch.no_grad():
        for s in range(0, len(items), a.batch_size):
            e = s + a.batch_size
            kw = dict(images=[it["image"] for it in items[s:e]],
                      categories=[it["category"] for it in items[s:e]],
                      llm_metadata=[it["llm_metadata"] for it in items[s:e]],
                      parses=[it["parse"] for it in items[s:e]], mlm_allowed=None)
            out_match = model.forward(free_texts=texts[s:e], **kw)
            out_swap = model.forward(free_texts=swapped[s:e], **kw)
            itm_ok += int((out_match["itm_logits"].argmax(-1).cpu().numpy() == 1).sum())
            itm_ok += int((out_swap["itm_logits"].argmax(-1).cpu().numpy() == 0).sum())
            itm_n += 2 * (e - s)
            cat_ok += int((out_match["category_logits"].argmax(-1).cpu().numpy()
                           == cat_t[s:e]).sum())
            sea_pred = out_match["season_logits"].argmax(-1).cpu().numpy()
            valid = sea_t[s:e] != -100
            sea_ok += int((sea_pred[valid] == sea_t[s:e][valid]).sum())
            sea_n += int(valid.sum())
    print(f"[eval] ITM acc: {itm_ok / max(itm_n, 1):.3f} | "
          f"category acc: {cat_ok / len(items):.3f} | "
          f"season acc: {sea_ok / max(sea_n, 1):.3f} ({sea_n} valid)")


if __name__ == "__main__":
    main()

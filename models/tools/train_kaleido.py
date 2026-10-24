"""
Semantic-KaleidoBERT training loop - all three self-supervised heads are trained:

  ITM      does the caption describe this garment image?         (positives vs negatives)
  category which of the 13 DeepFashion2 categories is it?
  MLM      recover masked caption words (intrinsic attributes only: colour /
           material / pattern) from the other words AND the image patches.
           Only on ITM-positive pairs.

Season is NOT a training head: captions never name a season, so no supervision
exists for one. Season suitability is decided at recommendation time from
weather/destination context plus garment metadata (VLM seasons list / LLM).

total = w_itm*ITM + w_cat*category + w_mlm*MLM
Landmarks / masks come from the enriched CSV (GT from the DeepFashion2 json) through GarmentParse.
"""
import os
import sys
import argparse
import torch
import torch.nn.functional as F
from torch.utils.data import DataLoader
from tqdm import tqdm


from model.kaleido.semantic_kaleido_model import SemanticKaleidoBERT
from model.tools.kaleido_training_dataset import KaleidoTrainingDataset, kaleido_collate_fn


def masked_ce(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """Cross-entropy that ignores target == -100. A batch without any valid target gives 0, not NaN."""
    if bool((target != -100).any()):
        return F.cross_entropy(logits, target, ignore_index=-100)
    return logits.sum() * 0.0


def _acc(logits, target):
    valid = target != -100
    n = int(valid.sum())
    if n == 0:
        return 0, 0
    return int((logits.argmax(-1)[valid] == target[valid]).sum()), n


def train_one_epoch(model, dataloader, optimizer, device="cuda", w=None):
    w = w or {"itm": 1.0, "cat": 1.0, "mlm": 1.0}
    model.train()
    sums = {k: 0.0 for k in ("total", "itm", "cat", "mlm")}
    hits = {k: [0, 0] for k in ("itm", "cat", "mlm")}
    pbar = tqdm(dataloader, desc="Training Epoch")
    for batch in pbar:
        optimizer.zero_grad()
        itm_t = batch["itm_target"]
        outputs = model(
            batch["image"], batch["category"], batch["llm_metadata"], batch["free_text"],
            parses=batch["parse"],
            mlm_allowed=(itm_t == 1),            # MLM only where the text really describes the image
        )
        dev = outputs["itm_logits"].device
        itm_t, cat_t = itm_t.to(dev), batch["category_target"].to(dev)

        l_itm = F.cross_entropy(outputs["itm_logits"], itm_t)
        l_cat = F.cross_entropy(outputs["category_logits"], cat_t)
        mlm_logits = outputs["mlm_logits"].flatten(0, 1)          # [B*L, vocab]
        mlm_t = outputs["mlm_labels"].flatten()                   # [B*L]
        l_mlm = masked_ce(mlm_logits, mlm_t)

        loss = w["itm"] * l_itm + w["cat"] * l_cat + w["mlm"] * l_mlm
        loss.backward()
        optimizer.step()

        sums["total"] += loss.item(); sums["itm"] += l_itm.item(); sums["cat"] += l_cat.item()
        sums["mlm"] += l_mlm.item()
        with torch.no_grad():
            for k, (lg, tg) in {"itm": (outputs["itm_logits"], itm_t), "cat": (outputs["category_logits"], cat_t),
                                "mlm": (mlm_logits, mlm_t)}.items():
                c, n = _acc(lg, tg)
                hits[k][0] += c; hits[k][1] += n
        pbar.set_postfix({"loss": f"{loss.item():.3f}", "itm": f"{l_itm.item():.2f}", "cat": f"{l_cat.item():.2f}",
                          "mlm": f"{l_mlm.item():.2f}"})
    n_batches = max(len(dataloader), 1)
    stats = {f"loss_{k}": v / n_batches for k, v in sums.items()}
    stats.update({f"acc_{k}": (c / n if n else float("nan")) for k, (c, n) in hits.items()})
    return stats


def eval_one_epoch(model, dataloader, device="cuda"):
    """Validation evidence (no gradients): loss + accuracy per head."""
    model.eval()
    sums = {k: 0.0 for k in ("total", "itm", "cat")}
    hits = {k: [0, 0] for k in ("itm", "cat")}
    with torch.no_grad():
        for batch in dataloader:
            itm_t = batch["itm_target"]
            outputs = model(
                batch["image"], batch["category"], batch["llm_metadata"], batch["free_text"],
                parses=batch["parse"], mlm_allowed=None,  # eval: no MLM corruption
            )
            dev = outputs["itm_logits"].device
            itm_t, cat_t = itm_t.to(dev), batch["category_target"].to(dev)
            l_itm = F.cross_entropy(outputs["itm_logits"], itm_t)
            l_cat = F.cross_entropy(outputs["category_logits"], cat_t)
            sums["total"] += (l_itm + l_cat).item()
            sums["itm"] += l_itm.item(); sums["cat"] += l_cat.item()
            for k, (lg, tg) in {"itm": (outputs["itm_logits"], itm_t),
                                "cat": (outputs["category_logits"], cat_t)}.items():
                c, n = _acc(lg, tg)
                hits[k][0] += c; hits[k][1] += n
    n_batches = max(len(dataloader), 1)
    stats = {f"loss_{k}": v / n_batches for k, v in sums.items()}
    stats.update({f"acc_{k}": (c / n if n else float("nan")) for k, (c, n) in hits.items()})
    return stats


def _save(model, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # SemanticKaleidoBERT is a plain wrapper (no state_dict): save the 3 trained modules.
    torch.save({"transformer": model.transformer.state_dict(),
                "heads": model.heads.state_dict(),
                "backbone": model.visual_backbone.state_dict()}, path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train_csv", default="preprocessed_data/enriched_train.csv",
                   help="enriched CSV that already contains fashion_caption + landmarks")
    p.add_argument("--val_csv", default="",
                   help="optional enriched validation CSV (evaluated every epoch, no gradients)")
    p.add_argument("--images_dir", default="")
    p.add_argument("--samples", type=int, default=20000)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--batch_size", type=int, default=8)
    p.add_argument("--lr", type=float, default=3e-5)
    p.add_argument("--w_itm", type=float, default=1.0)
    p.add_argument("--w_cat", type=float, default=1.0)
    p.add_argument("--w_mlm", type=float, default=1.0)
    p.add_argument("--save", default="checkpoints/kaleido_v2.pth")
    p.add_argument("--save_every", type=int, default=1,
                   help="save a checkpoint every N epochs (Colab disconnect safety)")
    p.add_argument("--resume", default="",
                   help="warm-start from a checkpoint (optimizer restarts fresh)")
    p.add_argument("--freeze_backbone", action="store_true",
                   help="freeze Swin (train transformer+heads only): low-RAM / early epochs")
    a = p.parse_args()
    weights = {"itm": a.w_itm, "cat": a.w_cat, "mlm": a.w_mlm}

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[Train] device={device} | csv={a.train_csv} | loss weights={weights}")

    ds = KaleidoTrainingDataset(preprocessed_csv=a.train_csv, images_base_dir=a.images_dir,
                                sample_size=a.samples, is_training=True)
    loader = DataLoader(ds, batch_size=a.batch_size, shuffle=True,
                        collate_fn=kaleido_collate_fn, num_workers=0)
    val_loader = None
    if a.val_csv:
        val_ds = KaleidoTrainingDataset(preprocessed_csv=a.val_csv, images_base_dir=a.images_dir,
                                        sample_size=None, is_training=False)
        val_loader = DataLoader(val_ds, batch_size=a.batch_size, shuffle=False,
                                collate_fn=kaleido_collate_fn, num_workers=0)
    model = SemanticKaleidoBERT(hidden_dim=768, num_layers=4, num_heads=8).to(device)
    if a.freeze_backbone:
        for prm in model.visual_backbone.parameters():
            prm.requires_grad_(False)
        print("[train] Swin backbone frozen.")
    if a.resume:
        model.load_checkpoint(a.resume, device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=a.lr)

    for ep in range(a.epochs):
        st = train_one_epoch(model, loader, optimizer, device, weights)
        print(f"Epoch {ep + 1}/{a.epochs} | loss {st['loss_total']:.4f} "
              f"(itm {st['loss_itm']:.3f}, cat {st['loss_cat']:.3f}, mlm {st['loss_mlm']:.3f}) | "
              f"acc itm {st['acc_itm']:.3f} cat {st['acc_cat']:.3f} mlm {st['acc_mlm']:.3f}")
        if val_loader is not None:
            vs = eval_one_epoch(model, val_loader, device)
            print(f"  [val] loss {vs['loss_total']:.4f} | acc itm {vs['acc_itm']:.3f} "
                  f"cat {vs['acc_cat']:.3f}")
        if (ep + 1) % max(a.save_every, 1) == 0:
            _save(model, a.save)
            print(f"  [ckpt] saved {a.save}")

    _save(model, a.save)
    print(f"Saved: {a.save}")


if __name__ == "__main__":
    main()

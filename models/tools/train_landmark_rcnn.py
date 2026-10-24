#!/usr/bin/env python3
"""Stage-3 training: fine-tune Keypoint R-CNN on DeepFashion2 (294 category-owned slots).

Two data layouts (pass exactly one):
  --csv CSV_PATH        single CSV (path + b_box + category_id + --lm_col)
  --json_dir JSON_DIR   official train/annos JSONs + --images_dir

Writes one checkpoint for DF2KeypointRCNN.predict_parse at inference time.
Kaleido TRAINING does not need this (it uses GT landmarks); new wardrobe photos do.
Needs a GPU.

Example:
    python3 train_landmark_rcnn.py --csv /content/data/train.csv \\
        --images_dir /content/data/images --lm_col landmarks \\
        --save /content/drive/MyDrive/kaleido/checkpoints/df2_keypoint_rcnn.pth
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model.kaleido.df2_keypoint_rcnn import finetune_keypoint_rcnn, finetune_keypoint_rcnn_csv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="", help="single-CSV layout (path + b_box + category_id + landmarks)")
    ap.add_argument("--lm_col", default="landmarks", help="landmarks column name in --csv")
    ap.add_argument("--json_dir", default="", help="official train/annos JSONs (alternative to --csv)")
    ap.add_argument("--images_dir", default="", help="image folder (unneeded when CSV paths are absolute)")
    ap.add_argument("--save", default="checkpoints/df2_keypoint_rcnn.pth")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch_size", type=int, default=2)
    ap.add_argument("--lr", type=float, default=0.002)
    ap.add_argument("--limit", type=int, default=0, help="0 = all rows/files")
    ap.add_argument("--device", default=None, help="default: cuda if available")
    a = ap.parse_args()
    if bool(a.csv) == bool(a.json_dir):
        ap.error("pass exactly one of --csv or --json_dir")
    if a.csv:
        finetune_keypoint_rcnn_csv(a.csv, a.images_dir, lm_col=a.lm_col, save_path=a.save,
                                   epochs=a.epochs, batch_size=a.batch_size, lr=a.lr,
                                   limit=(a.limit or None), device=a.device)
    else:
        if not a.images_dir:
            ap.error("--json_dir needs --images_dir")
        finetune_keypoint_rcnn(a.json_dir, a.images_dir, save_path=a.save, epochs=a.epochs,
                               batch_size=a.batch_size, lr=a.lr,
                               limit=(a.limit or None), device=a.device)


if __name__ == "__main__":
    main()

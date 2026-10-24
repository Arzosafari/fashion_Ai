# vision/trainer.py
import os
import torch
from ultralytics import YOLO

class Yolo26Trainer:
    """
    Dedicated trainer for the YOLO26 model on clothing datasets
    """
    def __init__(self, base_model: str = "yolo26n.pt"):
        self.base_model = base_model

    def train_model(
        self,
        data_yaml_path: str,
        epochs: int = 50,
        img_size: int = 640,
        batch_size: int = 16
    ):
        if not os.path.exists(data_yaml_path):
            raise FileNotFoundError(f"Dataset file not found: {data_yaml_path}")

        print(f"[YOLO26 Trainer] Starting model training based on {self.base_model}...")
        model = YOLO(self.base_model)

        device_target = 0 if torch.cuda.is_available() else "cpu"
        
        model.train(
            data=data_yaml_path,
            epochs=epochs,
            imgsz=img_size,
            batch=batch_size,
            device=device_target,
            project="experiments/yolo_train",
            name="garment_detector_yolo26",
            save=True
        )
        print("[YOLO26 Trainer] YOLO26 training completed successfully.")
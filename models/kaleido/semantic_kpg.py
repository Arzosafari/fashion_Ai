# semantic_kpg.py
import numpy as np
import torch
import torch.nn as nn
import torchvision.transforms as T
from PIL import Image
from typing import Optional, Tuple

try:
    from model.kaleido.garment_parse import GarmentParse
    from model.kaleido.kpg_geometry import PatchPlanner, NUM_PATCHES
except ImportError:
    from garment_parse import GarmentParse
    from kpg_geometry import PatchPlanner, NUM_PATCHES


class SemanticKPG(nn.Module):
    """
    Semantic Kaleido Patch Generator.

    The garment image (already cropped by cropper.py) is cut into 9 patches:
    global, upper_boundary, torso, side, hem and 4 fabric-texture windows.
    Regions come from a GarmentParse (keypoints + mask produced offline by Match R-CNN
    or taken from DeepFashion2 ground truth). Without a parse, it falls back to fixed
    proportions of the image (legacy behaviour). All geometry lives in kpg_geometry.py.
    """
    def __init__(self, crop_size: int = 224, mask_background: bool = True):
        super().__init__()
        self.crop_size = crop_size
        self.planner = PatchPlanner(mask_background=mask_background)
        self.last_info = {}
        self.transform = T.Compose([
            T.Resize((crop_size, crop_size)),
            T.ToTensor(),
            T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])

    def forward(
        self,
        image: Image.Image,
        parse: Optional[GarmentParse] = None,
        category: str = "top",
    ) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Returns:
            patches: [9, 3, S, S]  (invalid slots are zeros = mean colour after normalization)
            coords:  [9, 5]        normalized [x1, y1, x2, y2, area]
            valid:   [9] bool      False for slots that do not exist / could not be located
        """
        patches, coords, valid, info = self.planner.plan(image, parse, category)
        self.last_info = info

        tensors = []
        for p in patches:
            if p is None:
                tensors.append(torch.zeros(3, self.crop_size, self.crop_size))
            else:
                tensors.append(self.transform(p))
        return (
            torch.stack(tensors, dim=0),
            torch.from_numpy(coords),
            torch.from_numpy(valid),
        )


if __name__ == "__main__":
    img = Image.new("RGB", (400, 600), color=(180, 190, 200))
    kpg = SemanticKPG(crop_size=224)
    patches, coords, valid = kpg(img, category="top")
    print("Semantic-KPG executed successfully!")
    print(patches.shape, coords.shape, valid.tolist())

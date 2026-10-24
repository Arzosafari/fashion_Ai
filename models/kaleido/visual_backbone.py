import torch
import torch.nn as nn
import torchvision.models as models


class SwinVisualBackbone(nn.Module):
    """
    Visual encoder: Swin-T features + 5D spatial coords [x1, y1, x2, y2, area].
    Patches are processed in small chunks so the model fits in RAM without OOM.
    Pretrained ImageNet weights are ON by default: learning vision from scratch
    on 20k fashion crops is not a fair fight.
    """
    def __init__(self, hidden_dim: int = 768, pretrained: bool = True):
        super().__init__()
        swin = models.swin_t(weights=models.Swin_T_Weights.DEFAULT if pretrained else None)
        self.features = swin.features
        self.norm = swin.norm
        self.avgpool = swin.avgpool

        self.spatial_proj = nn.Sequential(
            nn.Linear(5, 128),
            nn.LayerNorm(128),
            nn.GELU(),
            nn.Linear(128, hidden_dim)
        )
        self.layer_norm = nn.LayerNorm(hidden_dim)

    def forward(self, patches: torch.Tensor, spatial_coords: torch.Tensor, chunk_size: int = 3) -> torch.Tensor:
        """Chunked patch encoding (chunks of 3) to avoid OOM."""
        num_patches = patches.shape[0]
        visual_embs = []

        for i in range(0, num_patches, chunk_size):
            chunk = patches[i: i + chunk_size]
            x = self.features(chunk)
            x = self.norm(x)
            x = x.permute(0, 3, 1, 2)
            x = self.avgpool(x)
            flat = torch.flatten(x, 1)
            visual_embs.append(flat)

        visual_emb = torch.cat(visual_embs, dim=0)  # [num_patches, 768]
        spatial_emb = self.spatial_proj(spatial_coords)  # [num_patches, 768]

        final_patch_emb = self.layer_norm(visual_emb + spatial_emb)
        return final_patch_emb

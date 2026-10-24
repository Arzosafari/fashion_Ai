from __future__ import annotations
import httpx
from trend_system.config import get_sources_config
from trend_system.collectors.global_sources.vogue import VogueAdapter
from trend_system.collectors.global_sources.harpers_bazaar import HarpersBazaarAdapter
from trend_system.collectors.global_sources.whowhatwear import WhoWhatWearAdapter
from trend_system.collectors.global_sources.wgsn import WGSNAdapter
# Iranian adapters preserved for archive but not registered for global scope (trend_scope=global)
# from trend_system.collectors.iranian_sources.digikala_mag import DigikalaMagAdapter
# from trend_system.collectors.iranian_sources.banimag import BaniMagAdapter
# from trend_system.collectors.iranian_sources.modeworld import ModeworldAdapter

ADAPTER_MAP = {
    "vogue": VogueAdapter,
    "harpers_bazaar": HarpersBazaarAdapter,
    "whowhatwear": WhoWhatWearAdapter,
    "wgsn": WGSNAdapter,
    # global scope: Iranian adapters disabled
    # "digikala_mag": DigikalaMagAdapter,
    # "banimode_mag": BaniMagAdapter,
    # "modeworld": ModeworldAdapter,
}

def get_enabled_collectors(http_client: httpx.AsyncClient | None = None):
    cfg = get_sources_config()
    collectors=[]
    for src in cfg.get("sources", []):
        sid = src["source_id"]
        if not src.get("enabled"):
            continue
        cls = ADAPTER_MAP.get(sid)
        if cls:
            collectors.append(cls(src, http_client))
    return collectors

def get_adapter(source_id: str, source_config: dict, http_client: httpx.AsyncClient | None = None):
    cls = ADAPTER_MAP.get(source_id)
    if not cls:
        return None
    return cls(source_config, http_client)

def get_all_sources():
    return get_sources_config().get("sources", [])

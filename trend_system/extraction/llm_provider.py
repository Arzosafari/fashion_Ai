from __future__ import annotations
import abc
import hashlib
import json
import logging
from typing import Protocol, Dict, Any, Optional

logger = logging.getLogger(__name__)

class LLMProvider(Protocol):
    async def extract(self, text: str, title: str | None, taxonomy_hint: list[str], language: str) -> Dict[str, Any]: ...

class DummyProvider:
    """Never fails, returns empty — system works without LLM."""
    async def extract(self, text: str, title: str | None, taxonomy_hint: list[str], language: str) -> Dict[str, Any]:
        return {"garments":[],"colors":[],"patterns":[],"styles":[],"materials":[],"silhouettes":[],"outfit_combinations":[],"trend_candidates":[]}

class OpenAIProvider:
    def __init__(self, model: str, api_key: str, api_base: str | None, timeout: int = 15):
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.timeout = timeout

    async def extract(self, text: str, title: str | None, taxonomy_hint: list[str], language: str) -> Dict[str, Any]:
        import httpx
        # Minimal openai-compatible call
        url = (self.api_base.rstrip("/") if self.api_base else "https://api.openai.com/v1") + "/chat/completions"
        prompt = f"""Extract fashion attributes. Taxonomy hints: {taxonomy_hint}
Title: {title}
Text: {text[:800]}
Language: {language}
Return ONLY JSON: {{"garments":[],"colors":[],"patterns":[],"styles":[],"materials":[],"silhouettes":[],"outfit_combinations":[],"trend_candidates":[]}}"""
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        body = {
            "model": self.model,
            "messages": [{"role":"user","content": prompt}],
            "temperature": 0.2,
            "response_format": {"type":"json_object"} if "gpt" in self.model else None
        }
        # remove None
        if body["response_format"] is None:
            body.pop("response_format")
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except:
                # try extract JSON block
                import re
                m = re.search(r"\{.*\}", content, re.S)
                if m:
                    return json.loads(m.group(0))
                return {}

def get_llm_provider() -> LLMProvider:
    from trend_system.config import get_llm_config, get_settings
    settings = get_settings()
    llm_cfg = get_llm_config()
    enabled = llm_cfg.get("enabled", False)
    # env override
    if settings.LLM_ENABLED is not None:
        enabled = settings.LLM_ENABLED
    if not enabled:
        return DummyProvider()
    provider = llm_cfg.get("provider", "dummy")
    if settings.LLM_PROVIDER:
        provider = settings.LLM_PROVIDER
    model = llm_cfg.get("model", "dummy")
    if settings.LLM_MODEL:
        model = settings.LLM_MODEL
    if provider == "dummy":
        return DummyProvider()
    api_key = settings.LLM_API_KEY or llm_cfg.get("api_key", "")
    if not api_key:
        logger.warning("LLM enabled but no API key — falling back to DummyProvider")
        return DummyProvider()
    api_base = settings.LLM_API_BASE or llm_cfg.get("api_base")
    timeout = llm_cfg.get("timeout", 15)
    if provider == "openai":
        return OpenAIProvider(model, api_key, api_base, timeout)
    # For anthropic/local, could add classes; fallback to OpenAIProvider for now (many local are openai-compatible)
    return OpenAIProvider(model, api_key, api_base, timeout)

def llm_cache_key(content_hash: str, prompt_version: str, taxonomy_version: str, provider_model: str) -> str:
    raw = f"{content_hash}:{prompt_version}:{taxonomy_version}:{provider_model}"
    return hashlib.sha256(raw.encode()).hexdigest()

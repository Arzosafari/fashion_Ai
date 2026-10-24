from __future__ import annotations
import logging
import httpx
from trend_system.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

class VogueAdapter(BaseCollector):
    async def discover_urls(self, http_client: httpx.AsyncClient) -> list[str]:
        urls: list[str] = []
        sitemap_error: str | None = None
        rss_error: str | None = None
        if self.sitemap_url:
            try:
                sitemap_urls = await self._fetch_sitemap_urls(self.sitemap_url, http_client, limit=150)
                urls.extend(sitemap_urls)
            except Exception as e:
                sitemap_error = str(e)
                logger.warning(f"vogue sitemap failed: {e}")
        if self.rss_url:
            try:
                rss_urls = await self._fetch_rss_urls(self.rss_url, http_client)
                urls.extend(rss_urls)
            except Exception as e:
                rss_error = str(e)
                logger.warning(f"vogue rss failed: {e}")
        if not urls and (sitemap_error or rss_error):
            raise RuntimeError(f"discovery failed for {self.source_id}: sitemap_error={sitemap_error} rss_error={rss_error}")
        # dedup preserve order
        seen = set()
        uniq = []
        for u in urls:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        return uniq

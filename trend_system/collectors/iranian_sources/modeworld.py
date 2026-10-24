from __future__ import annotations
import httpx
from trend_system.collectors.base import BaseCollector

class ModeworldAdapter(BaseCollector):
    async def discover_urls(self, http_client: httpx.AsyncClient) -> list[str]:
        import logging
        logger = logging.getLogger(__name__)
        urls: list[str] = []
        sitemap_error: str | None = None
        rss_error: str | None = None
        if self.sitemap_url:
            try:
                urls.extend(await self._fetch_sitemap_urls(self.sitemap_url, http_client, limit=150))
            except Exception as e:
                sitemap_error = str(e)
                logger.warning(f"modeworld sitemap failed: {e}")
        if self.rss_url:
            try:
                urls.extend(await self._fetch_rss_urls(self.rss_url, http_client))
            except Exception as e:
                rss_error = str(e)
                logger.warning(f"modeworld rss failed: {e}")
        if not urls and (sitemap_error or rss_error):
            raise RuntimeError(f"discovery failed for {self.source_id}: sitemap_error={sitemap_error} rss_error={rss_error}")
        seen=set(); uniq=[]
        for u in urls:
            if u not in seen:
                seen.add(u); uniq.append(u)
        return uniq

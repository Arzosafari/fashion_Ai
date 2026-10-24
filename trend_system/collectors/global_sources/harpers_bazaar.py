from __future__ import annotations
import logging
import httpx
from trend_system.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

class HarpersBazaarAdapter(BaseCollector):
    """Harper's Bazaar — seasonal trend reports, runway summaries.
    Sitemap: https://www.harpersbazaar.com/sitemap_index.xml
    Verified: robots allows *, sitemap_index contains content-tag, brand-tag etc.
    Use for multi-trend roundups (e.g., '15 Trends from Fall 2026 Runways').
    """
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
                logger.warning(f"harpers_bazaar sitemap failed: {e}")
        if self.rss_url:
            try:
                rss_urls = await self._fetch_rss_urls(self.rss_url, http_client)
                urls.extend(rss_urls)
            except Exception as e:
                rss_error = str(e)
                logger.warning(f"harpers_bazaar rss failed: {e}")
        if not urls and (sitemap_error or rss_error):
            raise RuntimeError(f"discovery failed for {self.source_id}: sitemap_error={sitemap_error} rss_error={rss_error}")
        seen=set(); uniq=[]
        for u in urls:
            if u not in seen:
                seen.add(u); uniq.append(u)
        # Filter to likely article URLs (harpersbazaar.com/fashion, trends, runway)
        # Keep broad but prefer fashion content; if sitemap returns tag pages, they will be filtered by is_allowed and later by extraction (no_fashion)
        return uniq

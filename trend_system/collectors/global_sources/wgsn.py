from __future__ import annotations
import logging
import httpx
from trend_system.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

class WGSNAdapter(BaseCollector):
    """WGSN — professional forecasting, macro trends.
    Official: https://www.wgsn.com/sitemap.xml
    IMPORTANT: robots.txt blocks * (Disallow: /) except allowlisted bots.
    This adapter MUST respect robots.txt, paywalls, auth.
    If content cannot be legally retrieved (403/401/paywall), gracefully skip — do NOT bypass.
    Authority high (0.95) when legally accessible; otherwise discovery will return 0 with error logged, and health will mark degraded, not fatal.
    """
    async def discover_urls(self, http_client: httpx.AsyncClient) -> list[str]:
        urls: list[str] = []
        sitemap_error: str | None = None
        rss_error: str | None = None
        if self.sitemap_url:
            try:
                sitemap_urls = await self._fetch_sitemap_urls(self.sitemap_url, http_client, limit=80)
                urls.extend(sitemap_urls)
            except Exception as e:
                # For WGSN, a failure is EXPECTED due to robots/paywall — log at INFO not warning, and do not raise if we can skip
                sitemap_error = str(e)
                logger.info(f"wgsn sitemap not accessible (expected for paywall/robots): {e}")
        if self.rss_url:
            try:
                rss_urls = await self._fetch_rss_urls(self.rss_url, http_client)
                urls.extend(rss_urls)
            except Exception as e:
                rss_error = str(e)
                logger.info(f"wgsn rss not accessible: {e}")
        # For WGSN, do NOT raise if both fail — return empty and let caller mark degraded but not fatal.
        # The source is forecasting-grade; skipping is allowed per spec.
        if not urls and (sitemap_error or rss_error):
            # Log but return empty; caller will treat as 0 discovered with no fatal error for WGSN.
            # To make health reporting honest, we raise a soft error that run_collector will catch as degraded.
            # Keep raise for consistency with other adapters, but run_collector handles it as failed source (partial).
            # Alternative: return [] silently. We choose to raise so per_source errors are visible, but not crash pipeline.
            raise RuntimeError(f"discovery failed for {self.source_id} (expected paywall/robots): sitemap_error={sitemap_error} rss_error={rss_error}")
        seen=set(); uniq=[]
        for u in urls:
            if u not in seen:
                seen.add(u); uniq.append(u)
        return uniq

    async def fetch_document(self, url: str, http_client: httpx.AsyncClient):
        # Enforce graceful skip: if robots disallows or paywall, return error without bypass attempt
        from trend_system.utils.robots import fetch_robots_txt, is_allowed_by_robots
        try:
            robots = await fetch_robots_txt(url, http_client)
            if robots and not is_allowed_by_robots(url, robots_content=robots):
                logger.info(f"wgsn robots disallow, skipping {url}")
                from trend_system.collectors.base import FetchResult
                return FetchResult(url=url, status=0, content=None, headers={}, error="robots disallow")
        except Exception:
            pass
        # Delegate to base with paywall check: if 401/403/402, treat as skip
        result = await super().fetch_document(url, http_client)
        if result.status in (401, 402, 403, 451):
            logger.info(f"wgsn paywall/auth required for {url}: HTTP {result.status}, skipping gracefully")
            result.error = f"paywall/auth HTTP {result.status}"
            result.content = None
        return result

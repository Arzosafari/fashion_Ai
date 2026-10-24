from __future__ import annotations
import abc
import hashlib
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from trend_system.utils.robots import is_allowed_by_robots

logger = logging.getLogger(__name__)

@dataclass
class FetchResult:
    url: str
    status: int
    content: str | None
    headers: dict
    error: str | None = None

@dataclass
class CollectionResult:
    source_id: str
    discovered_urls: int = 0
    fetched: int = 0
    new_documents: int = 0
    duplicates: int = 0
    errors: list[str] = field(default_factory=list)

class BaseCollector(abc.ABC):
    def __init__(self, source_config: dict, http_client: httpx.AsyncClient | None = None):
        self.config = source_config
        self.source_id = source_config["source_id"]
        self.enabled = source_config.get("enabled", True)
        self.sitemap_url = source_config.get("sitemap_url")
        self.rss_url = source_config.get("rss_url")
        self._http = http_client

    def can_fetch(self, url: str, robots_content: str | None = None) -> bool:
        if not self.enabled:
            return False
        return is_allowed_by_robots(url, robots_content=robots_content)

    @abc.abstractmethod
    async def discover_urls(self, http_client: httpx.AsyncClient) -> list[str]:
        """Return list of article URLs via sitemap/RSS."""
        ...

    async def fetch_document(self, url: str, http_client: httpx.AsyncClient) -> FetchResult:
        for attempt in range(3):
            try:
                resp = await http_client.get(url, headers={"Accept": "text/html"})
                return FetchResult(url=url, status=resp.status_code, content=resp.text if resp.status_code==200 else None, headers=dict(resp.headers), error=None if resp.status_code==200 else f"HTTP {resp.status_code}")
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt == 2:
                    return FetchResult(url=url, status=0, content=None, headers={}, error=str(e))
                import asyncio
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                return FetchResult(url=url, status=0, content=None, headers={}, error=str(e))
        return FetchResult(url=url, status=0, content=None, headers={}, error="unknown")

    async def collect(self, http_client: httpx.AsyncClient) -> CollectionResult:
        if not self.enabled:
            return CollectionResult(source_id=self.source_id, errors=["disabled"])
        result = CollectionResult(source_id=self.source_id)
        try:
            urls = await self.discover_urls(http_client)
            result.discovered_urls = len(urls)
            return result
        except Exception as e:
            logger.exception(f"collector {self.source_id} discover failed: {e}")
            result.errors.append(str(e))
            return result

    async def _fetch_sitemap_urls(self, sitemap_url: str, http_client: httpx.AsyncClient, limit: int = 200) -> list[str]:
        try:
            resp = await http_client.get(sitemap_url, timeout=20)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            msg = f"sitemap fetch failed for {self.source_id} url {sitemap_url}: {type(e).__name__}: {e}"
            logger.warning(msg)
            raise RuntimeError(msg) from e
        except Exception as e:
            msg = f"sitemap fetch failed for {self.source_id} url {sitemap_url}: {e}"
            logger.warning(msg)
            raise RuntimeError(msg) from e
        if resp.status_code != 200:
            msg = f"sitemap fetch failed for {self.source_id} url {sitemap_url}: HTTP {resp.status_code}"
            logger.warning(msg)
            raise RuntimeError(msg)
        raw = resp.content
        text: str
        if sitemap_url.endswith(".gz") or (len(raw) >= 2 and raw[:2] == b"\x1f\x8b"):
            try:
                import gzip
                text = gzip.decompress(raw).decode("utf-8", errors="ignore")
            except Exception as e:
                logger.warning(f"gzip decompress failed for {sitemap_url}: {e}")
                text = resp.text
        else:
            text = resp.text
        import re
        locs = re.findall(r"<loc>(.*?)</loc>", text)
        if not locs:
            return []
        is_index = "sitemap" in sitemap_url.lower() or any("sitemap" in l.lower() for l in locs[:3])
        if is_index:
            all_urls: list[str] = []
            sub_errors: list[str] = []
            for sub in sorted(locs, key=lambda x: 0 if "content" in x.lower() else 1)[:6]:
                if sub.endswith(".xml") or "sitemap" in sub.lower():
                    try:
                        sub_urls = await self._fetch_sitemap_urls(sub, http_client, limit=limit - len(all_urls))
                        all_urls.extend(sub_urls)
                    except Exception as e:
                        sub_errors.append(str(e))
                        logger.warning(f"sub-sitemap {sub} failed: {e}")
                        continue
                    if len(all_urls) >= limit:
                        break
                else:
                    all_urls.append(sub)
                if len(all_urls) >= limit:
                    break
            if not all_urls and sub_errors:
                raise RuntimeError(f"sitemap index {sitemap_url} all sub-fetches failed: {'; '.join(sub_errors)}")
            return all_urls[:limit]
        return locs[:limit]

    async def _fetch_rss_urls(self, rss_url: str, http_client: httpx.AsyncClient) -> list[str]:
        try:
            resp = await http_client.get(rss_url, timeout=15)
        except (httpx.TimeoutException, httpx.ConnectError) as e:
            msg = f"rss fetch failed for {self.source_id} url {rss_url}: {type(e).__name__}: {e}"
            logger.warning(msg)
            raise RuntimeError(msg) from e
        except Exception as e:
            msg = f"rss fetch failed for {self.source_id} url {rss_url}: {e}"
            logger.warning(msg)
            raise RuntimeError(msg) from e
        if resp.status_code != 200:
            msg = f"rss fetch failed for {self.source_id} url {rss_url}: HTTP {resp.status_code}"
            logger.warning(msg)
            raise RuntimeError(msg)
        import re
        links = re.findall(r"<link>(https?://[^<]+)</link>", resp.text)
        filtered = [l for l in links if "vogue.com" in l or "harpersbazaar.com" in l or "whowhatwear.com" in l or "wgsn.com" in l or "http" in l]
        return filtered[:100]

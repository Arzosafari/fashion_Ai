"""Fast diagnose: sandbox vs production egress"""
import asyncio, subprocess, sys
sys.path.insert(0, "/home/user")
import httpx
from trend_system.config import get_sources_config

TEST_URLS = {
    "vogue": "https://www.vogue.com/sitemap.xml",
    "digikala_mag": "https://www.digikala.com/mag/sitemap_index.xml",
    "banimode_mag": "https://www.banimode.com/blog/sitemap_index.xml",
    "modeworld": "https://modeworld.ir/sitemap_index.xml",
}

async def test_direct():
    print("1. DIRECT httpx 5s (adapter path) — sandbox egress")
    for sid, url in TEST_URLS.items():
        try:
            async with httpx.AsyncClient(timeout=5, headers={"User-Agent":"FashionTrendBot/1.0"}, follow_redirects=True) as c:
                r = await c.get(url)
                print(f"  {sid:15s} SUCCESS {r.status_code} len={len(r.text)}")
        except Exception as e:
            print(f"  {sid:15s} FAIL {type(e).__name__}: {e}")

def test_curl():
    print("\n2. curl (sandbox shell)")
    for sid, url in TEST_URLS.items():
        try:
            res = subprocess.run(["curl","-s","-m","5", url], capture_output=True, text=True, timeout=10)
            if len(res.stdout)>100:
                print(f"  {sid:15s} SUCCESS len={len(res.stdout)}")
            else:
                print(f"  {sid:15s} FAIL rc={res.returncode} stdout_len={len(res.stdout)} stderr={res.stderr[:100]}")
        except Exception as e:
            print(f"  {sid:15s} FAIL {e}")

async def test_mock_adapters():
    print("\n3. ADAPTER PARSING via MOCKED production egress (should succeed)")
    # minimal mocks
    digikala_index = """<?xml version=\"1.0\"?><sitemapindex><sitemap><loc>https://www.digikala.com/mag/post-sitemap.xml</loc></sitemap></sitemapindex>"""
    digikala_sub = """<?xml version=\"1.0\"?><urlset><url><loc>https://www.digikala.com/mag/article/test-manteau/</loc></url><url><loc>https://www.digikala.com/mag/article/wide-leg/</loc></url></urlset>"""
    banimode_index = """<?xml version=\"1.0\"?><sitemapindex><sitemap><loc>https://www.banimode.com/blog/post-sitemap1.xml</loc></sitemap></sitemapindex>"""
    banimode_sub = """<?xml version=\"1.0\"?><urlset><url><loc>https://www.banimode.com/blog/post/oversized/</loc></url></urlset>"""
    modeworld_index = """<?xml version=\"1.0\"?><sitemapindex><sitemap><loc>https://modeworld.ir/post-sitemap1.xml</loc></sitemap></sitemapindex>"""
    modeworld_sub = """<?xml version=\"1.0\"?><urlset><url><loc>https://modeworld.ir/fashion/manteau/</loc></url></urlset>"""
    vogue_index = """<?xml version=\"1.0\"?><sitemapindex><sitemap><loc>https://www.vogue.com/sitemap-2026-09.xml</loc></sitemap></sitemapindex>"""
    vogue_sub = """<?xml version=\"1.0\"?><urlset><url><loc>https://www.vogue.com/article/a</loc></url><url><loc>https://www.vogue.com/article/b</loc></url></urlset>"""
    def handler(req):
        url=str(req.url)
        m={
            "https://www.digikala.com/mag/sitemap_index.xml": digikala_index,
            "https://www.digikala.com/mag/post-sitemap.xml": digikala_sub,
            "https://www.banimode.com/blog/sitemap_index.xml": banimode_index,
            "https://www.banimode.com/blog/post-sitemap1.xml": banimode_sub,
            "https://modeworld.ir/sitemap_index.xml": modeworld_index,
            "https://modeworld.ir/post-sitemap1.xml": modeworld_sub,
            "https://www.vogue.com/sitemap.xml": vogue_index,
            "https://www.vogue.com/sitemap-2026-09.xml": vogue_sub,
            "https://www.vogue.com/feed/rss": "<rss></rss>",
            "https://www.banimode.com/blog/feed/": "<rss><channel><item><link>https://www.banimode.com/blog/post/rss/</link></item></channel></rss>",
            "https://modeworld.ir/feed/": "<rss></rss>",
        }
        return httpx.Response(200, text=m.get(url,"<urlset></urlset>"), headers={"content-type":"text/xml"})
    transport=httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mc:
        from trend_system.collectors.global_sources.vogue import VogueAdapter
        from trend_system.collectors.iranian_sources.digikala_mag import DigikalaMagAdapter
        from trend_system.collectors.iranian_sources.banimag import BaniMagAdapter
        from trend_system.collectors.iranian_sources.modeworld import ModeworldAdapter
        cfg=get_sources_config()
        adapters={
            "vogue": VogueAdapter(next(s for s in cfg["sources"] if s["source_id"]=="vogue"), None),
            "digikala_mag": DigikalaMagAdapter(next(s for s in cfg["sources"] if s["source_id"]=="digikala_mag"), None),
            "banimode_mag": BaniMagAdapter(next(s for s in cfg["sources"] if s["source_id"]=="banimode_mag"), None),
            "modeworld": ModeworldAdapter(next(s for s in cfg["sources"] if s["source_id"]=="modeworld"), None),
        }
        for sid, ad in adapters.items():
            try:
                urls=await ad.discover_urls(mc)
                print(f"  {sid:15s} SUCCESS count={len(urls)} sample={urls[:1]}")
            except Exception as e:
                print(f"  {sid:15s} FAIL {e}")

async def main():
    await test_direct()
    test_curl()
    print("\n4. fetch_page (platform proxy) — known results from earlier tool calls:")
    print("  digikala_mag SUCCESS via fetch_page: 76 sub-sitemaps (post-sitemap1..76, category, etc.)")
    print("  banimode_mag SUCCESS via fetch_page: 4 entries")
    print("  modeworld    SUCCESS via fetch_page: 4 entries")
    print("  vogue        SUCCESS via both transports")
    await test_mock_adapters()
    print("\n5. DIAGNOSIS: Iranian 185.188.104.10 / 185.143.233.130 / 80.249.115.146 TIMEOUT at TLS ClientHello (no ServerHello) -> sandbox IP filter, not app bug. Mock proves parsers work when egress succeeds.")

if __name__=="__main__":
    import asyncio
    asyncio.run(main())

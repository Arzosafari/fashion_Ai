"""Integration tests: Global Fashion Trend Module inside the Fashion AI app.

These tests are fully offline (no external site is contacted).  They verify:

* the existing FastAPI app still serves voice/text + weather endpoints and
  now also exposes the trend API;
* an empty trend database is handled gracefully;
* ingestion → snapshot → API returns the documented schema;
* the request-understanding pipeline receives an *optional* trend context
  without breaking the weather context;
* no background scheduler job is registered by the application, and the
  opt-in scheduler refuses duplicate job ids.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

ARTICLE_HTML = """<html><head>
<title>Fall 2026 Trend Report: Red Tailoring and Wide-Leg Trousers</title>
<meta property="article:published_time" content="{published}"/>
</head><body><article>
<p>Red tailoring and scarlet suiting dominated Paris Fashion Week for Fall/Winter 2026.
Wide-leg trousers in linen and wool were styled with dramatic bows, animal print
coats and elevated bomber jackets. Editors at Vogue, Harper's Bazaar and Who What
Wear agree that statement belts and sculptural ruffles are the defining looks of
the season, worn from morning meetings to evening events in New York, London,
Milan and Copenhagen.{suffix}</p>
</article></body></html>"""


@pytest.fixture()
def temp_trend_db(tmp_path, monkeypatch):
    """Point the trend module at a fresh SQLite file for the duration of a test."""
    db_path = tmp_path / "trends_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("SYNC_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("USE_SQLITE", raising=False)

    from trend_system import bootstrap as bootstrap_mod
    from trend_system.config import get_settings
    from trend_system.database import session as session_mod

    get_settings.cache_clear()
    session_mod.reset_engine_cache()
    bootstrap_mod.reset_bootstrap_flag()
    yield db_path
    get_settings.cache_clear()
    session_mod.reset_engine_cache()
    bootstrap_mod.reset_bootstrap_flag()


def _seed() -> None:
    from trend_system.bootstrap import bootstrap_trend_module

    asyncio.run(bootstrap_trend_module(force_seed=True))


def _ingest_and_snapshot():
    from trend_system.database.session import get_async_sessionmaker
    from trend_system.ingestion.pipeline import ingest_url
    from trend_system.scheduler.snapshot import materialize_snapshot

    published = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _run():
        async with get_async_sessionmaker()() as session:
            first = await ingest_url(
                session,
                "vogue",
                "https://www.vogue.com/article/fall-2026-trend-report",
                ARTICLE_HTML.format(published=published, suffix=""),
            )
            second = await ingest_url(
                session,
                "whowhatwear",
                "https://www.whowhatwear.com/fall-2026-trend-report",
                ARTICLE_HTML.format(
                    published=published,
                    suffix=" Who What Wear adds that brown suede and statement belts complete the look.",
                ),
            )
            payload = await materialize_snapshot(
                session,
                datetime.now(timezone.utc),
                exclude_synthetic=True,
                generated_by="integration-test",
            )
            return first, second, payload

    return asyncio.run(_run())


def test_empty_database_is_graceful(temp_trend_db):
    from trend_system.main import create_app as create_trend_app

    client = TestClient(create_trend_app())
    current = client.get("/api/v1/trends/current")
    assert current.status_code == 200
    assert current.json()["trends"] == []

    rec = client.get("/api/v1/trends/for-recommendation")
    assert rec.status_code == 200
    assert rec.json()["trends"] == []

    context = client.get("/api/v1/trends/context")
    assert context.status_code == 200
    body = context.json()
    assert body["available"] is False
    assert body["status"] in ("no_snapshot", "unavailable")


def test_ingestion_snapshot_and_api_schema(temp_trend_db):
    _seed()
    first, second, payload = _ingest_and_snapshot()

    assert first["status"] == "ingested", first
    assert first["signals"] >= 3
    assert second["status"] == "ingested", second
    assert payload, "snapshot must contain trends"

    concepts = {t["canonical_name"] for t in payload}
    assert "red_tailoring" in concepts or "wide_leg_bottom" in concepts, concepts

    ranked = sorted(payload, key=lambda t: t["trend_score"], reverse=True)
    top = ranked[0]
    for key in (
        "trend",
        "canonical_name",
        "category",
        "trend_score",
        "current_score",
        "lifecycle",
        "evidence_count",
        "supporting_sources",
        "explanation",
        "components",
    ):
        assert key in top, f"missing {key} in snapshot entry"

    from trend_system.main import create_app as create_trend_app

    client = TestClient(create_trend_app())
    current = client.get("/api/v1/trends/current", params={"limit": 10})
    assert current.status_code == 200
    body = current.json()
    assert body["snapshot_time_utc"]
    assert body["trends"], body
    assert body["trends"][0]["canonical_name"]

    rec = client.get("/api/v1/trends/for-recommendation", params={"limit": 5})
    assert rec.status_code == 200
    rec_body = rec.json()
    assert rec_body["trends"]
    assert len(rec_body["trends"]) <= 5
    assert {"canonical_name", "trend_score", "lifecycle"} <= set(rec_body["trends"][0])

    ctx = client.get("/api/v1/trends/context", params={"limit": 3})
    assert ctx.status_code == 200
    ctx_body = ctx.json()
    assert ctx_body["available"] is True
    assert 1 <= len(ctx_body["trends"]) <= 3


class _StubResolver:
    def resolve_for_request(self, structured_request, fallback_location=None,
                            fallback_latitude=None, fallback_longitude=None):
        return None


class _StubWeatherService:
    """Minimal stand-in so the test never touches the network."""

    def __init__(self):
        self.location_resolver = _StubResolver()

    def _fetch_for_resolved_location(self, resolved_loc, date_or_time=None):
        from fashion_stt.models import WeatherContext

        return WeatherContext(
            available=False,
            status="missing_location",
            message="stubbed weather service (offline test)",
        )

    def _classify_exception(self, exc):
        return "provider_error", str(exc)

    def _unavailable(self, status, message, mode=None, forecast_for=None):
        from fashion_stt.models import WeatherContext

        return WeatherContext(
            available=False,
            status=status,
            message=message,
            mode=mode,
            forecast_for=forecast_for,
        )


def test_existing_app_keeps_weather_and_adds_trend_context(temp_trend_db):
    _seed()
    from fashion_stt.server import create_app

    app = create_app(weather_service=_StubWeatherService())
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        health_body = health.json()
        assert health_body["status"] == "healthy"
        assert health_body["language"] == "en"
        assert health_body["modules"]["global_trends"]["integrated"] is True

        # existing endpoints still registered
        paths = set(app.openapi()["paths"].keys())
        assert "/api/weather" in paths
        assert "/api/understand" in paths
        assert "/api/transcribe" in paths
        assert "/api/v1/trends/for-recommendation" in paths
        assert "/api/v1/trends/context" in paths

        response = client.post(
            "/api/understand",
            json={"text": "I need an outfit for a wedding in Paris next weekend"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["structured_data"]["intent"]["type"] == "outfit_recommendation"
        assert "weather_context" in body
        trend_ctx = body["recommendation_context"]["trend_context"]
        assert trend_ctx is not None, "trend context must be attached to the aggregate context"
        assert trend_ctx["status"] in ("ok", "no_snapshot")
        # Weather remains independent and available=False for the stub
        assert body["recommendation_context"]["weather_context"]["available"] is False


def test_no_background_scheduler_registered():
    import fashion_stt.server as server_module
    from trend_system.scheduler.jobs import (
        COLLECTION_JOB_ID,
        SNAPSHOT_JOB_ID,
        configure_jobs,
    )

    app = server_module.create_app(weather_service=_StubWeatherService())
    assert getattr(app.state, "scheduler", None) is None

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    configure_jobs(scheduler)
    configure_jobs(scheduler)  # idempotent: must not duplicate jobs

    job_ids = [job.id for job in scheduler.get_jobs()]
    assert job_ids.count(COLLECTION_JOB_ID) == 1
    assert job_ids.count(SNAPSHOT_JOB_ID) == 1
    assert len(job_ids) == 2


@pytest.mark.asyncio
async def test_collector_discovery_parses_sitemap_offline():
    """Sitemap discovery is verified with a mocked transport (no live site)."""
    import httpx

    from trend_system.collectors.global_sources.vogue import VogueAdapter

    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset>
      <url><loc>https://www.vogue.com/article/fall-trends</loc></url>
      <url><loc>https://www.vogue.com/article/red-tailoring</loc></url>
      <url><loc>https://www.vogue.com/article/wide-leg-trousers</loc></url>
    </urlset>"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = VogueAdapter(
            {
                "source_id": "vogue",
                "sitemap_url": "https://www.vogue.com/sitemap.xml",
                "rss_url": None,
            },
            client,
        )
        urls = await adapter.discover_urls(client)

    assert "https://www.vogue.com/article/fall-trends" in urls
    assert len(urls) == 3


def test_robots_policy_is_respected():
    from trend_system.utils.robots import is_allowed_by_robots

    wgsn_robots = "User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nAllow: /\n"
    assert is_allowed_by_robots("https://www.wgsn.com/en/trends", wgsn_robots) is False

    vogue_robots = "User-agent: *\nDisallow: /search\n"
    assert is_allowed_by_robots("https://www.vogue.com/article/fall-trends", vogue_robots) is True
    assert is_allowed_by_robots("https://www.vogue.com/search?q=bows", vogue_robots) is False


def test_sentence_transformer_embedding_path(monkeypatch):
    """Exercise the Sentence-Transformers branch without downloading a model.

    The real ``sentence-transformers`` + ``torch`` stack is optional; here a stub
    model proves the embedding code path (and not only the lexical fallback) can
    merge semantically related concepts.
    """
    import trend_system.normalization.semantic_cluster as sc

    class _FakeModel:
        def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
            return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(sc, "_load_sentence_transformer", lambda: _FakeModel())
    clusterer = sc.SemanticClusterer(threshold=0.58, use_embeddings=True)
    clusters = clusterer.cluster(
        [
            {"canonical": "quiet luxury tailoring", "category": "styling"},
            {"canonical": "understated elegant suiting", "category": "styling"},
        ]
    )
    assert len(clusters) == 1, "stub embeddings should merge the two concepts"

    monkeypatch.setattr(sc, "_load_sentence_transformer", lambda: None)
    fallback = sc.SemanticClusterer(threshold=0.58, use_embeddings=True)
    separate = fallback.cluster(
        [
            {"canonical": "quiet luxury tailoring", "category": "styling"},
            {"canonical": "understated elegant suiting", "category": "styling"},
        ]
    )
    assert len(separate) == 2, "lexical fallback must not merge unrelated concepts"


def test_existing_app_survives_missing_trend_module(monkeypatch):
    """If the trend package cannot be imported, the voice/text + weather app
    must still start, serve its endpoints and simply omit trend context."""
    import fashion_stt.server as server_module

    monkeypatch.setattr(server_module, "TREND_MODULE_AVAILABLE", False)
    monkeypatch.setattr(server_module, "trend_api_router", None)
    monkeypatch.setattr(server_module, "bootstrap_trend_module", None)
    monkeypatch.setattr(server_module, "get_global_trend_context", None)

    app = server_module.create_app(weather_service=_StubWeatherService())
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "healthy"
        assert health["modules"]["global_trends"]["integrated"] is False

        paths = set(app.openapi()["paths"])
        assert "/api/understand" in paths
        assert "/api/weather" in paths
        assert "/api/v1/trends/context" not in paths

        response = client.post("/api/understand", json={"text": "a light jacket for tomorrow"})
        assert response.status_code == 200
        body = response.json()
        assert body["structured_data"]["intent"]["type"] == "outfit_recommendation"
        assert body["recommendation_context"]["trend_context"] is None
        assert body["recommendation_context"]["weather_context"]["available"] is False


@pytest.mark.asyncio
async def test_collection_to_snapshot_end_to_end_offline(temp_trend_db):
    """Full chain with fixtures: sitemap discovery → article fetch → ingestion →
    observations/signals → materialized snapshot. No external site is contacted."""
    from trend_system.bootstrap import bootstrap_trend_module

    await bootstrap_trend_module(force_seed=True)
    import httpx

    from trend_system.collectors.global_sources.vogue import VogueAdapter
    from trend_system.database.session import get_async_sessionmaker
    from trend_system.ingestion.pipeline import ingest_url
    from trend_system.scheduler.snapshot import materialize_snapshot

    article_url = "https://www.vogue.com/article/fallen-2026-trend-report"
    sitemap = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        f"<urlset><url><loc>{article_url}</loc></url></urlset>"
    )
    published = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    article = ARTICLE_HTML.format(published=published, suffix=" Statement belts completed every look.")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".xml"):
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        return httpx.Response(200, text=article, headers={"content-type": "text/html"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = VogueAdapter(
            {"source_id": "vogue", "sitemap_url": "https://www.vogue.com/sitemap.xml", "rss_url": None},
            client,
        )
        urls = await adapter.discover_urls(client)
        assert urls == [article_url]

        page = await adapter.fetch_document(urls[0], client)
        assert page.status == 200 and page.content

        async with get_async_sessionmaker()() as session:
            result = await ingest_url(session, "vogue", urls[0], page.content, page.headers)
            assert result["status"] == "ingested", result
            assert result["signals"] >= 3

            payload = await materialize_snapshot(
                session, datetime.now(timezone.utc), exclude_synthetic=True, generated_by="test"
            )
            assert payload, "snapshot must contain the ingested trends"
            concepts = {t["canonical_name"] for t in payload}
            assert {"red_tailoring", "wide_leg_bottom"} & concepts

            # historical rows are append-only: the snapshot was stored, not merged
            from sqlalchemy import func, select
            from trend_system.database.models import TrendSnapshot

            count = (await session.execute(select(func.count()).select_from(TrendSnapshot))).scalar()
            assert count == 1

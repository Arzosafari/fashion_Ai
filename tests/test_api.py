import pytest
from fastapi.testclient import TestClient

# Mock DB: we will test that API routes exist and handle empty snapshot gracefully
# Use in-memory SQLite override? For now, test that app imports and routes are mounted without DB.

def test_app_import():
    from trend_system.main import app
    assert app.title == "Fashion Trend Intelligence Pipeline"

def test_routes_exist():
    from trend_system.main import app
    paths = []
    for r in app.routes:
        if hasattr(r, "path"):
            paths.append(r.path)
        elif hasattr(r, "path_regex"):
            paths.append(str(r.path_regex))
        else:
            paths.append(str(r))
    # Check via OpenAPI
    openapi = app.openapi()
    openapi_paths = list(openapi["paths"].keys())
    assert any("/api/v1/trends/current" in p for p in openapi_paths)
    assert any("/api/v1/trends/for-recommendation" in p for p in openapi_paths)
    assert any("/health" in p for p in openapi_paths)

@pytest.mark.asyncio
async def test_llm_dummy():
    from trend_system.extraction.llm_provider import get_llm_provider
    provider = get_llm_provider()
    # default is dummy
    result = await provider.extract("test text", "title", ["wide_leg_bottom"], "en")
    assert "garments" in result
    assert isinstance(result["garments"], list)

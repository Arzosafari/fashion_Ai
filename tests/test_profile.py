"""Profile persistence, API, privacy and pipeline integration."""
import pytest
from fastapi.testclient import TestClient
from fashion_stt.server import create_app
from fashion_stt import profile

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('PROFILE_LOCAL_MODE', '1')
    url = f'sqlite+aiosqlite:///{tmp_path}/profiles.db'
    monkeypatch.setenv('PROFILE_DATABASE_URL', url)
    app = create_app(enable_trends=False)
    return TestClient(app)


def test_crud_patch_validation_and_restart(client):
    assert client.get('/api/v1/profile').status_code == 404
    assert client.patch('/api/v1/profile', json={'personal': {'city': 'Dallas'}}).status_code == 404
    created = client.put('/api/v1/profile', json={
        'personal': {'display_name':'A', 'city':'Dallas'},
        'style': {'preferred_styles':['minimalist'], 'preferred_colors':['navy']},
        'sizes': {'shoe_size':'9', 'shoe_size_system':'US'},
    })
    assert created.status_code == 200, created.text
    original = created.json()
    assert client.get('/api/v1/profile').json() == original
    patched = client.patch('/api/v1/profile', json={'style': {'preferred_colors':['white']}, 'personal': {'city':None}})
    assert patched.status_code == 200, patched.text
    assert patched.json()['personal']['display_name'] == 'A'
    assert patched.json()['personal']['city'] is None
    assert patched.json()['style']['preferred_styles'] == ['minimalist']
    assert patched.json()['style']['preferred_colors'] == ['white']
    assert patched.json()['id'] == original['id']
    assert client.patch('/api/v1/profile', json={'sizes': {'fit_preference':'wrong'}}).status_code == 422
    assert client.patch('/api/v1/profile', json={'style': {'preferred_styles':None}}).status_code == 422
    assert client.put('/api/v1/profile', json={'personal': {'password':'secret'}}).status_code == 422
    new_client = TestClient(create_app(enable_trends=False))
    assert new_client.get('/api/v1/profile').json() == patched.json()
    replaced = client.put('/api/v1/profile', json={'shopping':{'budget_level':'moderate'}}).json()
    assert replaced['id'] == original['id']
    assert replaced['personal']['display_name'] is None
    assert client.delete('/api/v1/profile').status_code == 204
    assert client.delete('/api/v1/profile').status_code == 404
    assert client.get('/api/v1/profile').status_code == 404


def test_opt_in_and_cross_origin(client, monkeypatch):
    assert client.put('/api/v1/profile', json={}).status_code == 200
    assert client.get('/api/v1/profile', headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.put('/api/v1/profile', json={}, headers={'Origin':'https://evil.example'}).status_code == 403
    monkeypatch.delenv('PROFILE_LOCAL_MODE')
    assert client.get('/api/v1/profile').status_code == 503
    result = client.post('/api/understand', json={'text':'Suggest an outfit'}).json()
    assert result['recommendation_context']['profile_context']['status'] == 'disabled'


def test_context_updates_and_failure_are_independent(client, monkeypatch):
    def ask(text='Suggest an outfit', method='text', headers=None):
        res = client.post('/api/understand', json={'text':text, 'input_method':method}, headers=headers)
        assert res.status_code == 200, res.text
        return res.json()['recommendation_context']
    ctx = ask()
    assert ctx['profile_context']['status'] == 'no_profile'
    assert 'weather_context' in ctx and 'trend_context' in ctx
    assert client.put('/api/v1/profile', json={
        'personal': {'display_name':'Private', 'city':'Dallas'},
        'style': {'preferred_styles':['minimalist'], 'preferred_colors':['navy'], 'style_inspiration':'private'},
        'sizes': {'shoe_size':'9', 'shoe_size_system':'US'},
        'restrictions': {'avoided_materials':['wool'], 'additional_notes':'private'},
    }).status_code == 200
    first = ask('Suggest an outfit')['profile_context']
    assert first['available'] and first['preferences']['preferred_colors'] == ['navy']
    assert 'shoe_size' not in first['preferences']
    assert 'Private' not in str(first) and 'Dallas' not in str(first) and 'private' not in str(first)
    shoes = ask('Suggest shoes', 'voice')['profile_context']['preferences']
    assert shoes['shoe_size'] == '9' and shoes['shoe_size_system'] == 'US'
    client.patch('/api/v1/profile', json={'style':{'preferred_colors':['white']}})
    next_ctx = ask('Suggest a colorful outfit tonight')['profile_context']
    assert next_ctx['preferences']['preferred_colors'] == ['white']
    assert client.get('/api/v1/profile').json()['style']['preferred_colors'] == ['white']
    assert ask(headers={'Origin':'https://evil.example'})['profile_context']['status'] == 'disabled'
    async def fail(): raise RuntimeError('db offline')
    monkeypatch.setattr(profile, 'load_profile', fail)
    assert ask()['profile_context']['status'] == 'unavailable'


def test_profile_page(client):
    res = client.get('/profile.html')
    assert res.status_code == 200
    assert 'Profile &amp; preferences' in res.text
    assert client.get('/profile.js').status_code == 200


def test_trend_and_weather_remain_independent(client, monkeypatch):
    import fashion_stt.server as server
    async def trend_ok(limit):
        return {'available': True, 'status': 'ok', 'trends': [], 'meta': {}}
    monkeypatch.setattr(server, 'get_global_trend_context', trend_ok)
    assert client.put('/api/v1/profile', json={'style':{'preferred_styles':['casual']}}).status_code == 200
    integrated = TestClient(create_app(enable_trends=True))
    res = integrated.post('/api/understand', json={'text':'Suggest an outfit'})
    ctx = res.json()['recommendation_context']
    assert ctx['trend_context']['status'] == 'ok'
    assert ctx['weather_context']['status'] == 'missing_location'
    assert ctx['profile_context']['preferences']['preferred_styles'] == ['casual']
    async def trend_fail(limit):
        raise RuntimeError('trend unavailable')
    monkeypatch.setattr(server, 'get_global_trend_context', trend_fail)
    ctx = integrated.post('/api/understand', json={'text':'Suggest an outfit'}).json()['recommendation_context']
    assert ctx['trend_context'] is None and ctx['profile_context']['available']


def test_concurrent_patches_preserve_unrelated_fields(client):
    from concurrent.futures import ThreadPoolExecutor
    assert client.put('/api/v1/profile', json={}).status_code == 200
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda payload: client.patch('/api/v1/profile', json=payload), [
            {'style': {'preferred_colors':['red']}},
            {'style': {'preferred_styles':['classic']}},
        ]))
    assert all(r.status_code == 200 for r in results)
    style = client.get('/api/v1/profile').json()['style']
    assert style['preferred_colors'] == ['red'] and style['preferred_styles'] == ['classic']

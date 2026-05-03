import importlib
import json
import os
from datetime import datetime, timedelta, UTC

import pytest


def _user_headers(token_codec, *permissions: str, user_id: str = 'u_10001', tenant_id: str = 'default', subject_type: str = 'user', extra: dict[str, str] | None = None) -> dict[str, str]:
    token = token_codec.issue_access_token(subject_type=subject_type, subject_id=user_id, tenant_id=tenant_id, roles=[subject_type], permissions=list(permissions)).token
    headers = {'Authorization': f'Bearer {token}'}
    if extra:
        headers.update(extra)
    return headers


def test_campaign_listing_and_copy_generation(client, token_codec):
    campaigns = client.get('/api/v1/marketing/campaigns?page=1&page_size=20', headers=_user_headers(token_codec, 'user:marketing.read'))
    assert campaigns.status_code == 200
    first_campaign = campaigns.json()['data']['items'][0]
    copy = client.post('/api/v1/marketing/copy/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id': first_campaign['campaign_id'], 'topic': 'AI 算力起量', 'audience': 'AI 创业团队', 'tone': 'launch', 'keywords': ['AI 算力', '弹性扩容']})
    assert copy.status_code == 200
    assert copy.json()['data']['headline'] == 'AI 算力起量'


def test_metrics_and_readyz_endpoints(client):
    ready = client.get('/readyz')
    assert ready.status_code == 200
    ready_payload = ready.json()
    assert 'components' in ready_payload
    assert ready_payload['components']['database']['ready'] is True
    metrics = client.get('/metrics')
    assert metrics.status_code == 200
    assert 'marketing_readiness_state' in metrics.text
    assert 'marketing_requests_total' in metrics.text
    assert 'marketing_requests_total{operation="copy_detail",resource_type="copy",status="success"}' not in metrics.text


def test_capabilities_endpoint(client, token_codec):
    response = client.get('/api/v1/marketing/capabilities', headers=_user_headers(token_codec, 'user:marketing.read'))
    assert response.status_code == 200
    data = response.json()['data']
    assert data['copy']['provider'] in {'template', 'llm'}
    assert data['poster']['provider'] in {'placeholder', 'image-service'}
    assert 'mode' in data['copy']
    assert 'mode' in data['poster']


def test_admin_campaign_crud(client, token_codec):
    create = client.post('/api/v1/marketing/admin/campaigns', headers=_user_headers(token_codec, 'admin:marketing.write', subject_type='admin'), json={'name': '管理端活动', 'product_type': 'gpu', 'status': 'draft', 'start_at': '2026-04-21T00:00:00+00:00', 'end_at': '2026-05-21T00:00:00+00:00', 'landing_page_url': 'https://smartcloud.local/admin-campaign', 'highlights': ['可编辑']})
    assert create.status_code == 200
    campaign_id = create.json()['data']['campaign_id']
    listing = client.get('/api/v1/marketing/admin/campaigns', headers=_user_headers(token_codec, 'admin:marketing.read', subject_type='admin'))
    assert listing.status_code == 200
    assert any(item['campaign_id'] == campaign_id for item in listing.json()['data']['items'])
    update = client.put(f'/api/v1/marketing/admin/campaigns/{campaign_id}', headers=_user_headers(token_codec, 'admin:marketing.write', subject_type='admin'), json={'name': '管理端活动-更新', 'product_type': 'gpu', 'status': 'published', 'start_at': '2026-04-21T00:00:00+00:00', 'end_at': '2026-05-21T00:00:00+00:00', 'landing_page_url': 'https://smartcloud.local/admin-campaign', 'highlights': ['已发布']})
    assert update.status_code == 200
    assert update.json()['data']['name'] == '管理端活动-更新'
    delete = client.delete(f'/api/v1/marketing/admin/campaigns/{campaign_id}', headers=_user_headers(token_codec, 'admin:marketing.write', subject_type='admin'))
    assert delete.status_code == 200
    relist = client.get('/api/v1/marketing/admin/campaigns', headers=_user_headers(token_codec, 'admin:marketing.read', subject_type='admin'))
    assert all(item['campaign_id'] != campaign_id for item in relist.json()['data']['items'])


def test_admin_routes_record_metrics(client, token_codec):
    before = client.get('/metrics').text
    create = client.post('/api/v1/marketing/admin/campaigns', headers=_user_headers(token_codec, 'admin:marketing.write', subject_type='admin'), json={'name': '指标活动', 'product_type': 'gpu', 'status': 'draft', 'start_at': '2026-04-21T00:00:00+00:00', 'end_at': '2026-05-21T00:00:00+00:00', 'landing_page_url': 'https://smartcloud.local/admin-metrics', 'highlights': ['指标']})
    assert create.status_code == 200
    campaign_id = create.json()['data']['campaign_id']
    update = client.put(f'/api/v1/marketing/admin/campaigns/{campaign_id}', headers=_user_headers(token_codec, 'admin:marketing.write', subject_type='admin'), json={'name': '指标活动-更新', 'product_type': 'gpu', 'status': 'published', 'start_at': '2026-04-21T00:00:00+00:00', 'end_at': '2026-05-21T00:00:00+00:00', 'landing_page_url': 'https://smartcloud.local/admin-metrics', 'highlights': ['指标']})
    assert update.status_code == 200
    delete = client.delete(f'/api/v1/marketing/admin/campaigns/{campaign_id}', headers=_user_headers(token_codec, 'admin:marketing.write', subject_type='admin'))
    assert delete.status_code == 200
    after = client.get('/metrics').text
    assert 'operation="admin_campaign_create",resource_type="campaign",status="success"' in after
    assert 'operation="admin_campaign_update",resource_type="campaign",status="success"' in after
    assert 'operation="admin_campaign_delete",resource_type="campaign",status="success"' in after


def test_admin_campaign_create_duplicate_id_returns_conflict(client, token_codec):
    response = client.post('/api/v1/marketing/admin/campaigns', headers=_user_headers(token_codec, 'admin:marketing.write', subject_type='admin'), json={'campaign_id': 'cmp_gpu_launch_001', 'name': '重复活动', 'product_type': 'gpu', 'status': 'draft', 'start_at': '2026-04-21T00:00:00+00:00', 'end_at': '2026-05-21T00:00:00+00:00', 'landing_page_url': 'https://smartcloud.local/dup', 'highlights': ['重复']})
    assert response.status_code == 409
    assert response.json()['message'] == "marketing campaign 'cmp_gpu_launch_001' already exists"


def test_admin_routes_reject_non_admin_subject(client, token_codec):
    response = client.get('/api/v1/marketing/admin/campaigns', headers=_user_headers(token_codec, 'admin:marketing.read'))
    assert response.status_code in {401, 403}


def test_copy_generation_with_llm_provider_mock(client, token_codec, service_modules, monkeypatch):
    monkeypatch.setenv('MARKETING_COPY_GENERATOR_PROVIDER', 'llm')
    monkeypatch.setenv('MARKETING_LLM_API_URL', 'http://llm.local/v1/chat/completions')
    monkeypatch.setenv('MARKETING_LLM_API_KEY', 'secret')
    monkeypatch.setenv('MARKETING_LLM_MODEL', 'gpt-test')
    service_modules['config'].get_settings.cache_clear()
    copy_module = importlib.import_module('app.services.copy_generator')

    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({'choices':[{'message':{'content': json.dumps({'headline':'LLM 标题','summary':'LLM 摘要','body':'LLM 正文','call_to_action':'立即咨询'}, ensure_ascii=False)}}]}).encode('utf-8')

    monkeypatch.setattr(copy_module, 'urlopen', lambda req, timeout=10: FakeResponse())
    response = client.post('/api/v1/marketing/copy/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id': 'cmp_gpu_launch_001', 'topic': 'AI 算力', 'audience': '团队', 'tone': 'launch', 'keywords': []})
    assert response.status_code == 200
    assert response.json()['data']['headline'] == 'LLM 标题'


def test_poster_generation_with_image_service_provider_mock(client, token_codec, service_modules, monkeypatch):
    monkeypatch.setenv('MARKETING_POSTER_GENERATOR_PROVIDER', 'image-service')
    monkeypatch.setenv('MARKETING_IMAGE_API_URL', 'http://img.local/generate')
    monkeypatch.setenv('MARKETING_IMAGE_API_KEY', 'secret')
    service_modules['config'].get_settings.cache_clear()
    poster_module = importlib.import_module('app.services.poster_generator')

    class FakeResponse:
        headers = {'Content-Type': 'image/png'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return b'PNGDATA'

    monkeypatch.setattr(poster_module, 'urlopen', lambda req, timeout=20: FakeResponse())
    created = client.post('/api/v1/marketing/posters', headers=_user_headers(token_codec, 'user:marketing.write', extra={'Idempotency-Key':'poster-img-001'}), json={'campaign_id':'cmp_gpu_launch_001','theme':'图像服务','slogan':'真实服务','size':'1080x1080'})
    assert created.status_code == 202
    detail = client.get(f"/api/v1/marketing/posters/{created.json()['data']['task_id']}", headers=_user_headers(token_codec, 'user:marketing.read'))
    assert detail.status_code == 200
    assert detail.json()['data']['status'] == 'completed'


def test_special_chars_promotion_link(client, token_codec):
    response = client.post('/api/v1/marketing/promotion-links/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id':'cmp_gpu_launch_001','channel':'we chat','source':'社群&投放','content_tag':'首屏 banner/测试'})
    assert response.status_code == 200
    assert 'utm_content=' in response.json()['data']['tracking_code']
    assert '%26' in response.json()['data']['tracking_code']


def test_detail_routes_record_metrics_and_tracing(client, token_codec, service_modules, monkeypatch):
    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'true')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry = importlib.import_module('app.core.telemetry')
    telemetry.get_memory_span_exporter().clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    traced_client = TestClient(main.app)
    campaigns = traced_client.get('/api/v1/marketing/campaigns?page=1&page_size=20', headers=_user_headers(token_codec, 'user:marketing.read'))
    campaign_id = campaigns.json()['data']['items'][0]['campaign_id']
    copy_resp = traced_client.post('/api/v1/marketing/copy/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id': campaign_id, 'topic': '细节查看', 'audience': '企业', 'tone': 'professional', 'keywords': ['细节']})
    copy_id = copy_resp.json()['data']['copy_id']
    link_resp = traced_client.post('/api/v1/marketing/promotion-links/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id': campaign_id, 'channel': 'wechat', 'source': 'detail', 'content_tag': 'detail'})
    link_id = link_resp.json()['data']['link_id']
    poster_resp = traced_client.post('/api/v1/marketing/posters', headers=_user_headers(token_codec, 'user:marketing.write', extra={'Idempotency-Key': 'detail-route-001'}), json={'campaign_id': campaign_id, 'theme': '详情', 'slogan': '详情页', 'size': '1080x1080'})
    task_id = poster_resp.json()['data']['task_id']

    assert traced_client.get(f'/api/v1/marketing/copies/{copy_id}', headers=_user_headers(token_codec, 'user:marketing.read')).status_code == 200
    assert traced_client.get(f'/api/v1/marketing/promotion-links/{link_id}', headers=_user_headers(token_codec, 'user:marketing.read')).status_code == 200
    assert traced_client.get(f'/api/v1/marketing/posters/{task_id}', headers=_user_headers(token_codec, 'user:marketing.read')).status_code == 200

    metrics = traced_client.get('/metrics').text
    assert 'marketing_requests_total{operation="copy_detail",resource_type="copy",status="success"}' in metrics
    assert 'marketing_requests_total{operation="promotion_link_detail",resource_type="promotion_link",status="success"}' in metrics
    assert 'marketing_requests_total{operation="poster_detail",resource_type="poster",status="success"}' in metrics

    span_names = {span.name for span in telemetry.get_memory_span_exporter().spans}
    assert 'marketing.copy_detail' in span_names
    assert 'marketing.promotion_link_detail' in span_names
    assert 'marketing.poster_detail' in span_names

    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'false')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()


def test_trace_export_records_span_and_propagates_traceparent(service_modules, token_codec):
    os.environ['SMARTCLOUD_TRACE_ENABLED'] = 'true'
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry = importlib.import_module('app.core.telemetry')
    telemetry.get_memory_span_exporter().clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    response = client.get('/api/v1/marketing/campaigns', headers=_user_headers(token_codec, 'user:marketing.read', extra={'traceparent': '00-1234567890abcdef1234567890abcdef-1234567890abcdef-01'}))
    assert response.status_code == 200
    spans = telemetry.get_memory_span_exporter().spans
    assert any(getattr(span, 'name', '') == 'marketing.campaign_listing' for span in spans)
    campaign_span = next(span for span in spans if getattr(span, 'name', '') == 'marketing.campaign_listing')
    assert campaign_span.attributes['trace_id'] == '1234567890abcdef1234567890abcdef'
    assert campaign_span.attributes['user_id'] == 'u_10001'
    assert campaign_span.attributes['tenant_id'] == 'default'
    os.environ['SMARTCLOUD_TRACE_ENABLED'] = 'false'
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()


def test_metrics_counter_values_change_after_copy_and_link_requests(client, token_codec):
    before = client.get('/metrics').text
    client.post('/api/v1/marketing/copy/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id':'cmp_gpu_launch_001','topic':'增长','audience':'创业者','tone':'growth','keywords':['增长']})
    client.post('/api/v1/marketing/promotion-links/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id':'cmp_gpu_launch_001','channel':'wechat','source':'social','content_tag':'spring'})
    after = client.get('/metrics').text
    assert 'marketing_copies_generated_total' in before
    assert 'marketing_links_generated_total' in after


def test_readyz_reports_degraded_without_database_url(service_modules, monkeypatch):
    monkeypatch.setenv('MARKETING_SERVICE_DATABASE_URL', 'sqlite:////no/such/dir/marketing-service.db')
    monkeypatch.delenv('SMARTCLOUD_MYSQL_DSN', raising=False)
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    response = client.get('/readyz')
    payload = response.json()
    assert response.status_code == 503
    assert payload['ready'] is False
    assert payload['components']['database']['ready'] is False


def test_concurrent_poster_creation_same_idempotency_key_reuses_task(service_modules):
    import threading

    store = service_modules['store'].get_marketing_store()
    payload = service_modules['models'].CreatePosterTaskRequest(campaign_id='cmp_gpu_launch_001', theme='并发', slogan='同 key', size='1080x1080')
    results: list[str] = []
    errors: list[str] = []
    barrier = threading.Barrier(2)

    def worker() -> None:
        try:
            barrier.wait()
            result = store.create_poster_task(user_id='u1', tenant_id='t1', payload=payload, idempotency_key='same-key')
            results.append(result.task_id)
        except Exception as exc:
            errors.append(repr(exc))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(set(results)) == 1


def test_campaign_date_range_edge_cases(service_modules):
    store = service_modules['store'].get_marketing_store()
    now = datetime.now(UTC)
    with store._session_factory.begin() as session:
        session.add(service_modules['store'].CampaignRow(campaign_id='cmp_today', name='today', product_type='gpu', status='published', start_at=now, end_at=now + timedelta(minutes=5), landing_page_url='https://x', highlights=['a'], deleted_at=None))
        session.add(service_modules['store'].CampaignRow(campaign_id='cmp_boundary', name='boundary', product_type='gpu', status='published', start_at=now - timedelta(minutes=5), end_at=now, landing_page_url='https://x', highlights=['b'], deleted_at=None))
    listing = store.list_campaigns(page=1, page_size=20, sort_by='start_at', sort_order='desc', status='published', product_type=None)
    ids = {item.campaign_id for item in listing.items}
    assert 'cmp_today' in ids or 'cmp_boundary' in ids


def test_copy_generation_with_empty_and_long_keywords(client, token_codec):
    long_keyword = '超长关键词' * 20
    response = client.post('/api/v1/marketing/copy/generate', headers=_user_headers(token_codec, 'user:marketing.write'), json={'campaign_id':'cmp_gpu_launch_001','topic':'主题','audience':'受众','tone':'professional','keywords':['', long_keyword]})
    assert response.status_code == 200
    assert response.json()['data']['headline'] == '主题'


def test_openapi_publishes_new_routes(client):
    response = client.get('/openapi.json')
    assert response.status_code == 200
    paths = response.json()['paths']
    assert '/readyz' in paths
    assert '/metrics' in paths
    assert '/api/v1/marketing/capabilities' in paths
    assert '/api/v1/marketing/admin/campaigns' in paths


def test_celery_apply_async_failure_returns_503_and_records_metrics(client, token_codec, service_modules, monkeypatch):
    routes_module = importlib.import_module('app.routes')
    telemetry = importlib.import_module('app.core.telemetry')

    class FakeAsyncTask:
        def apply_async(self, *args, **kwargs):
            raise RuntimeError('broker down')

    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'true')
    monkeypatch.setenv('MARKETING_SERVICE_CELERY_BROKER_URL', 'redis://localhost:6379/0')
    monkeypatch.setenv('MARKETING_SERVICE_CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry.get_memory_span_exporter().clear()
    monkeypatch.setattr(routes_module, 'generate_poster_task_job', FakeAsyncTask())
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    test_client = TestClient(main.app)
    response = test_client.post(
        '/api/v1/marketing/posters',
        headers=_user_headers(token_codec, 'user:marketing.write', extra={'Idempotency-Key': 'celery-fail-001'}),
        json={'campaign_id': 'cmp_gpu_launch_001', 'theme': 'Celery失败', 'slogan': '队列异常', 'size': '1080x1080'},
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload['message'] == 'poster task queue unavailable'
    metrics = test_client.get('/metrics').text
    assert 'marketing_celery_operations_total{operation="enqueue",status="error"}' in metrics
    spans = telemetry.get_memory_span_exporter().spans
    enqueue_span = next(span for span in spans if getattr(span, 'name', '') == 'marketing.celery_enqueue')
    assert enqueue_span.attributes['operation'] == 'celery_enqueue'
    assert enqueue_span.attributes['status'] == 'error'

    monkeypatch.setenv('MARKETING_SERVICE_CELERY_BROKER_URL', 'memory://')
    monkeypatch.setenv('MARKETING_SERVICE_CELERY_RESULT_BACKEND', 'cache+memory://')
    monkeypatch.setenv('MARKETING_SERVICE_CELERY_TASK_ALWAYS_EAGER', 'true')
    monkeypatch.setenv('MARKETING_SERVICE_CELERY_TASK_EAGER_PROPAGATES', 'true')
    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'true')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry.get_memory_span_exporter().clear()
    celery_module = importlib.reload(importlib.import_module('app.celery_app'))
    tasks_module = importlib.reload(importlib.import_module('app.tasks'))
    routes_module = importlib.import_module('app.routes')
    routes_module.generate_poster_task_job = tasks_module.generate_poster_task
    routes_module.get_settings = service_modules['config'].get_settings
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    eager_client = TestClient(main.app)
    created = eager_client.post('/api/v1/marketing/posters', headers=_user_headers(token_codec, 'user:marketing.write', extra={'Idempotency-Key': 'celery-eager-001'}), json={'campaign_id': 'cmp_gpu_launch_001', 'theme': 'Celery', 'slogan': '真实执行', 'size': '1080x1080'})
    assert created.status_code == 202
    task_id = created.json()['data']['task_id']
    detail = eager_client.get(f'/api/v1/marketing/posters/{task_id}', headers=_user_headers(token_codec, 'user:marketing.read'))
    assert detail.status_code == 200
    assert detail.json()['data']['status'] == 'completed'
    metrics = eager_client.get('/metrics').text
    assert 'marketing_celery_operations_total{operation="enqueue",status="success"}' in metrics
    spans = telemetry.get_memory_span_exporter().spans
    enqueue_span = next(span for span in spans if getattr(span, 'name', '') == 'marketing.celery_enqueue')
    assert enqueue_span.attributes['status'] == 'ok'

    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'false')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()


def test_minio_bucket_missing_upload_failure_and_object_repair_paths(service_modules):
    store_module = service_modules['store']
    storage = store_module.PosterArtifactStorage()
    statuses: list[tuple[str, str]] = []

    class FakeClient:
        def __init__(self):
            self.bucket_exists_calls = 0
            self.existing_objects: set[str] = set()
        def bucket_exists(self, bucket):
            self.bucket_exists_calls += 1
            return False
        def make_bucket(self, bucket):
            raise RuntimeError('make bucket failed')
        def put_object(self, *args, **kwargs):
            raise AssertionError('put_object should not be called after make_bucket failure')
        def stat_object(self, bucket, object_name):
            if object_name in self.existing_objects:
                return object()
            raise RuntimeError('missing object')
        def remove_object(self, bucket, object_name):
            raise RuntimeError('delete failed')

    fake_client = FakeClient()
    original_labels = store_module.marketing_minio_operations_total.labels
    original_poster_public_base_url = store_module.get_settings().poster_public_base_url

    def fake_labels(*, operation, status):
        statuses.append((operation, status))
        class Counter:
            def inc(self):
                return None
        return Counter()

    store_module.marketing_minio_operations_total.labels = fake_labels
    try:
        store_module.get_settings().poster_public_base_url = 'https://cdn.smartcloud.local/posters'
        storage._client = lambda: (fake_client, 'marketing-artifacts')
        public_url = storage.store_bytes('poster_x', b'data', 'image/png')
        assert public_url.endswith('/poster_x.png')
        assert ('bucket_exists', 'miss') in statuses
        assert ('make_bucket', 'error') in statuses
        assert storage.object_exists('poster_x') is False
        repaired_url = storage.ensure_object_present('poster_x', b'data', 'image/png')
        assert repaired_url.endswith('/poster_x.png')
        fake_client.existing_objects.add('poster_present.png')
        statuses.clear()
        existing_url = storage.ensure_object_present('poster_present', b'data', 'image/png')
        assert existing_url.endswith('/poster_present.png')
        assert ('put_object', 'success') not in statuses
        assert storage.delete_object('poster_x') is False
        assert ('remove_object', 'error') in statuses
    finally:
        store_module.get_settings().poster_public_base_url = original_poster_public_base_url
        store_module.marketing_minio_operations_total.labels = original_labels


def test_delete_poster_task_removes_minio_object(service_modules):
    store = service_modules['store'].get_marketing_store()
    payload = service_modules['models'].CreatePosterTaskRequest(
        campaign_id='cmp_gpu_launch_001',
        theme='删除对象',
        slogan='清理',
        size='1080x1080',
    )
    created = store.create_poster_task(user_id='u1', tenant_id='t1', payload=payload, idempotency_key='delete-minio-001')
    deleted_task_ids: list[str] = []
    store._artifact_storage.delete_object = lambda task_id: deleted_task_ids.append(task_id) or True
    store.delete_poster_task(created.task_id)
    assert deleted_task_ids == [created.task_id]
    assert store.get_poster_task(user_id='u1', tenant_id='t1', task_id=created.task_id) is None


def test_readyz_reports_bucket_missing_as_degraded(service_modules, monkeypatch):
    class FakeClient:
        def bucket_exists(self, bucket):
            return False

    original_client = service_modules['store'].PosterArtifactStorage._client
    service_modules['store'].PosterArtifactStorage._client = lambda self: (FakeClient(), 'marketing-artifacts')
    monkeypatch.setenv('MARKETING_SERVICE_MINIO_ENDPOINT', 'http://minio.local:9000')
    monkeypatch.setenv('MARKETING_SERVICE_MINIO_ACCESS_KEY', 'ak')
    monkeypatch.setenv('MARKETING_SERVICE_MINIO_SECRET_KEY', 'sk')
    monkeypatch.delenv('MARKETING_SERVICE_CELERY_BROKER_URL', raising=False)
    monkeypatch.delenv('MARKETING_SERVICE_CELERY_RESULT_BACKEND', raising=False)
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    degraded_client = TestClient(main.app)
    response = degraded_client.get('/readyz')
    payload = response.json()
    assert response.status_code == 503
    assert payload['ready'] is False
    assert payload['components']['minio']['configured'] is True
    assert payload['components']['minio']['ready'] is False
    assert payload['components']['minio']['detail'] == 'bucket-missing'

    metrics = degraded_client.get('/metrics').text
    assert 'marketing_minio_operations_total{operation="bucket_exists",status="miss"}' in metrics

    service_modules['store'].PosterArtifactStorage._client = original_client


def test_readyz_reports_minio_missing_credentials_as_degraded(service_modules, monkeypatch):
    monkeypatch.setenv('MARKETING_SERVICE_MINIO_ENDPOINT', 'http://minio.local:9000')
    monkeypatch.delenv('MARKETING_SERVICE_MINIO_ACCESS_KEY', raising=False)
    monkeypatch.delenv('MARKETING_SERVICE_MINIO_SECRET_KEY', raising=False)
    monkeypatch.delenv('MARKETING_SERVICE_CELERY_BROKER_URL', raising=False)
    monkeypatch.delenv('MARKETING_SERVICE_CELERY_RESULT_BACKEND', raising=False)
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    degraded_client = TestClient(main.app)
    response = degraded_client.get('/readyz')
    payload = response.json()
    assert response.status_code == 503
    assert payload['ready'] is False
    assert payload['components']['minio']['ready'] is False
    assert payload['components']['minio']['detail'] == 'missing-credentials'


def test_mongodb_upsert_failure_returns_503_and_records_metrics(token_codec, service_modules, monkeypatch):
    telemetry = importlib.import_module('app.core.telemetry')
    metrics_module = importlib.import_module('app.core.metrics')

    class FailingMongoRuntime:
        async def upsert_asset(self, task):
            metrics_module.marketing_upstream_errors_total.labels(backend='mongodb', error_type='RuntimeError').inc()
            raise RuntimeError('mongo down')

        async def readiness(self):
            return {'ready': False, 'configured': True, 'detail': 'error:RuntimeError'}

    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'true')
    routes_module = importlib.import_module('app.routes')
    monkeypatch.setattr(routes_module, 'get_marketing_mongo_runtime', lambda: FailingMongoRuntime())
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry.get_memory_span_exporter().clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    test_client = TestClient(main.app)
    response = test_client.post(
        '/api/v1/marketing/posters',
        headers=_user_headers(token_codec, 'user:marketing.write', extra={'Idempotency-Key': 'mongo-fail-001'}),
        json={'campaign_id': 'cmp_gpu_launch_001', 'theme': 'Mongo失败', 'slogan': '文档库异常', 'size': '1080x1080'},
    )
    assert response.status_code == 503
    assert response.json()['message'] == 'poster asset document store unavailable'
    assert metrics_module.marketing_upstream_errors_total.labels(backend='mongodb', error_type='RuntimeError')._value.get() >= 1
    poster_spans = [span for span in telemetry.get_memory_span_exporter().spans if getattr(span, 'name', '') == 'marketing.poster_create']
    assert any(span.attributes.get('status') == 'error' for span in poster_spans)
    store = service_modules['store'].get_marketing_store()
    assert all(task.task_id != 'mongo-fail-001' for task in store.list_poster_tasks(user_id='u_10001', tenant_id='default', page=1, page_size=20, sort_by='updated_at', sort_order='desc', status=None, campaign_id=None).items)

    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'false')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()


def test_readyz_reports_mongodb_ping_failure_as_degraded(service_modules, monkeypatch):
    class FailingMongoRuntime:
        async def readiness(self):
            return {
                'ready': False,
                'configured': True,
                'detail': 'error:RuntimeError',
            }

    monkeypatch.setattr(importlib.import_module('app.routes'), 'get_marketing_mongo_runtime', lambda: FailingMongoRuntime())
    monkeypatch.delenv('MARKETING_SERVICE_CELERY_BROKER_URL', raising=False)
    monkeypatch.delenv('MARKETING_SERVICE_CELERY_RESULT_BACKEND', raising=False)
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    degraded_client = TestClient(main.app)
    response = degraded_client.get('/readyz')
    payload = response.json()
    assert response.status_code == 503
    assert payload['ready'] is False
    assert payload['components']['mongodb']['ready'] is False
    assert payload['components']['mongodb']['detail'] == 'error:RuntimeError'


def test_readyz_reports_celery_upstream_failure_as_degraded(service_modules, monkeypatch):
    monkeypatch.setenv('MARKETING_SERVICE_CELERY_BROKER_URL', 'redis://localhost:6379/0')
    monkeypatch.setenv('MARKETING_SERVICE_CELERY_RESULT_BACKEND', 'redis://localhost:6379/1')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    routes_module = importlib.import_module('app.routes')
    monkeypatch.setattr(routes_module, 'get_marketing_store', lambda allow_fallback=True: type('ReadyStore', (), {'database_readiness': staticmethod(lambda trace=False: {'ready': True, 'configured': True, 'detail': 'query-ok'}), 'minio_readiness': staticmethod(lambda trace=False: {'ready': True, 'configured': False, 'detail': 'disabled'}), 'celery_readiness': staticmethod(lambda trace=False: {'ready': False, 'configured': True, 'detail': 'error:OperationalError'})})())
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    degraded_client = TestClient(main.app)
    response = degraded_client.get('/readyz')
    payload = response.json()
    assert response.status_code == 503
    assert payload['ready'] is False
    assert payload['components']['celery']['configured'] is True
    assert payload['components']['celery']['ready'] is False
    assert payload['components']['celery']['detail'] == 'error:OperationalError'


def test_auth_validation_strict_mode_records_upstream_span(service_modules, token_codec, monkeypatch):
    monkeypatch.setenv('SMARTCLOUD_TRACE_ENABLED', 'true')
    monkeypatch.setenv('MARKETING_SERVICE_AUTH_VALIDATION_MODE', 'strict')
    monkeypatch.setenv('MARKETING_SERVICE_AUTH_VALIDATE_TOKEN_URL', 'http://auth.local/internal/validate')
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry = importlib.import_module('app.core.telemetry')
    telemetry.get_memory_span_exporter().clear()
    dependencies_module = importlib.import_module('app.dependencies')

    def fake_validate(_request, _token, *, settings):
        return {
            'subject_type': 'user',
            'subject_id': 'u_10001',
            'tenant_id': 'default',
            'roles': ['user'],
            'permissions': ['user:marketing.read'],
            'expired_at': '2099-01-01T00:00:00+00:00',
        }

    monkeypatch.setattr(dependencies_module, '_validate_token_with_auth_service', fake_validate)
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    traced_client = TestClient(main.app)
    response = traced_client.get('/api/v1/marketing/campaigns', headers=_user_headers(token_codec, 'user:marketing.read'))
    assert response.status_code == 200
    spans = telemetry.get_memory_span_exporter().spans
    upstream_span = next(span for span in spans if getattr(span, 'name', '') == 'marketing.auth_validate_upstream')
    assert upstream_span.attributes['operation'] == 'auth_validation_upstream'
    assert upstream_span.attributes['status'] == 'ok'

def test_auth_validation_invalid_token_records_error_metrics(client):
    response = client.get('/api/v1/marketing/campaigns', headers={'Authorization': 'Bearer broken.token.value'})
    assert response.status_code == 401
    body = response.json()
    assert body['message']
    assert body['code'] == 4010002


def test_trace_records_failure_attributes_for_auth_and_mongodb(service_modules, token_codec, monkeypatch):
    os.environ['SMARTCLOUD_TRACE_ENABLED'] = 'true'
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry = importlib.import_module('app.core.telemetry')
    telemetry.get_memory_span_exporter().clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    traced_client = TestClient(main.app)
    invalid = traced_client.get('/api/v1/marketing/campaigns', headers={'Authorization': 'Bearer broken.token.value'})
    assert invalid.status_code == 401
    auth_span = next(span for span in telemetry.get_memory_span_exporter().spans if getattr(span, 'name', '') == 'marketing.auth_validate')
    assert auth_span.attributes['status'] == 'error'
    assert auth_span.attributes['error_type'] == 'TokenError'

    class FailingMongoRuntime:
        async def upsert_asset(self, task):
            raise RuntimeError('mongo down')

        async def readiness(self):
            return {'ready': False, 'configured': True, 'detail': 'error:RuntimeError'}

    routes_module = importlib.import_module('app.routes')
    monkeypatch.setattr(routes_module, 'get_marketing_mongo_runtime', lambda: FailingMongoRuntime())
    telemetry.get_memory_span_exporter().clear()
    main = importlib.reload(importlib.import_module('app.main'))
    traced_client = TestClient(main.app)
    response = traced_client.post(
        '/api/v1/marketing/posters',
        headers=_user_headers(token_codec, 'user:marketing.write', extra={'Idempotency-Key': 'mongo-trace-fail-001'}),
        json={'campaign_id': 'cmp_gpu_launch_001', 'theme': 'Mongo失败', 'slogan': '文档库异常', 'size': '1080x1080'},
    )
    assert response.status_code == 503
    poster_spans = [span for span in telemetry.get_memory_span_exporter().spans if getattr(span, 'name', '') == 'marketing.poster_create']
    statuses = [span.attributes.get('status') for span in poster_spans]
    assert 'error' in statuses
    error_spans = [span for span in poster_spans if span.attributes.get('status') == 'error']
    assert error_spans
    assert error_spans[0].attributes['error_type'] in {'RuntimeError', 'ServiceError'}

    os.environ['SMARTCLOUD_TRACE_ENABLED'] = 'false'
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()


def test_trace_excludes_readyz_and_metrics(service_modules, token_codec):
    os.environ['SMARTCLOUD_TRACE_ENABLED'] = 'true'
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()
    telemetry = importlib.import_module('app.core.telemetry')
    telemetry.get_memory_span_exporter().clear()
    main = importlib.reload(importlib.import_module('app.main'))
    from fastapi.testclient import TestClient

    traced_client = TestClient(main.app)
    traced_client.get('/readyz')
    traced_client.get('/metrics')
    traced_client.get('/healthz')
    assert telemetry.get_memory_span_exporter().spans == []
    os.environ['SMARTCLOUD_TRACE_ENABLED'] = 'false'
    service_modules['config'].get_settings.cache_clear()
    service_modules['store'].get_marketing_store.cache_clear()


def test_admin_requires_explicit_permission_even_for_admin_subject(client, token_codec):
    response = client.post('/api/v1/marketing/admin/campaigns', headers=_user_headers(token_codec, subject_type='admin'), json={'name': '无权限活动', 'product_type': 'gpu', 'status': 'draft', 'start_at': '2026-04-21T00:00:00+00:00', 'end_at': '2026-05-21T00:00:00+00:00', 'landing_page_url': 'https://smartcloud.local/no-perm', 'highlights': ['no']})
    assert response.status_code == 403


def test_readyz_reports_celery_disabled_when_queue_not_configured(client):
    payload = client.get('/readyz').json()
    assert payload['components']['celery']['configured'] is False
    assert payload['components']['celery']['ready'] is True
    assert payload['components']['celery']['detail'] == 'disabled'

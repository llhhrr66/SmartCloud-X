from __future__ import annotations

from celery import Celery

from app.core.config import get_settings


def build_celery_app() -> Celery:
    settings = get_settings()
    broker_url = settings.celery_broker_url or "memory://"
    result_backend = settings.celery_result_backend or "cache+memory://"
    visibility_timeout = max(
        settings.celery_visibility_timeout_seconds,
        settings.celery_time_limit_seconds + 60,
    )
    app = Celery("marketing-service")
    app.conf.update(
        broker_url=broker_url,
        result_backend=result_backend,
        imports=("app.tasks",),
        task_default_queue=settings.celery_queue_name,
        task_routes={"marketing.generate_poster_task": {"queue": settings.celery_queue_name}},
        task_track_started=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=settings.celery_task_eager_propagates,
        task_store_eager_result=True,
        worker_prefetch_multiplier=1,
        broker_transport_options={"visibility_timeout": visibility_timeout},
        result_backend_transport_options={"visibility_timeout": visibility_timeout},
        visibility_timeout=visibility_timeout,
    )
    return app


celery_app = build_celery_app()

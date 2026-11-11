"""
> Why: Configure the background task application for ingestion and scheduled alerts.
> Throughput: Worker concurrency is configured at deployment based on measured job load.
> Dependencies: Celery with Redis broker and validated application settings.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hometag",
    broker=settings.redis_url,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    task_ignore_result=True,
    task_serializer="json",
    timezone="UTC",
)

"""Celery application configured for the ETL pipeline.

Broker: Redis (shared with cache layer, different DB index)
Queues: per-platform queues to avoid cross-platform interference
Serializer: JSON
"""

from celery import Celery

from app.infra.settings import settings

app = Celery(
    "marketing_analytics_etl",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.etl.tasks"],
)

# ------------------------------------------------------------------
# Celery configuration
# ------------------------------------------------------------------

app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="Asia/Bangkok",
    enable_utc=True,
    # Task settings
    task_acks_late=True,  # Re-deliver if worker crashes mid-task
    task_reject_on_worker_lost=True,
    # Retry
    task_default_retry_delay=60,  # 1 minute base
    task_max_retries=5,
    # Queues — one per platform for isolation
    task_routes={
        "app.etl.tasks.fetch_and_land": {"queue": "fetch"},
        "app.etl.tasks.normalize_and_stage": {"queue": "normalize"},
        "app.etl.tasks.load_to_fact": {"queue": "load"},
    },
    # Result backend TTL (we don't need results forever)
    result_expires=3600,
)


if __name__ == "__main__":
    app.start()
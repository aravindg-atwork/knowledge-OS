from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "knowledge_hub",
    broker=_settings.CELERY_BROKER_URL,
    backend=_settings.CELERY_RESULT_BACKEND,
    include=["app.workers.tasks_sync", "app.workers.tasks_ingestion"],
)

celery_app.conf.update(
    task_routes={
        "app.workers.tasks_sync.*": {"queue": "sync"},
        "app.workers.tasks_ingestion.*": {"queue": "ingestion"},
    },
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "poll-google-drive-mock-every-5-minutes": {
            "task": "app.workers.tasks_sync.sync_all_connectors_task",
            "schedule": 300.0,
        },
    },
)

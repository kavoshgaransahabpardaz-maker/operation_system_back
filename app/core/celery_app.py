from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "brokerai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.agents.email_collector.tasks",
        "app.agents.document_classifier.tasks",
        "app.agents.shipment_matcher.tasks",
        "app.agents.intel_collector.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "app.agents.email_collector.tasks.*": {"queue": "email"},
        "app.agents.document_classifier.tasks.*": {"queue": "classification"},
        "app.agents.shipment_matcher.tasks.*": {"queue": "matching"},
    },
    beat_schedule={
        "sync-all-mailboxes": {
            "task": "app.agents.email_collector.tasks.sync_all_mailboxes",
            "schedule": crontab(minute="*/5"),
        },
        "poll-intel-sources": {
            "task": "tasks.poll_all_sources",
            "schedule": crontab(minute=0),  # every hour
        },
    },
)

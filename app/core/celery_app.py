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
        "tasks.poll_all_sources": {"queue": "intel_collect"},
        "tasks.poll_source": {"queue": "intel_collect"},
        "tasks.poll_intel_source": {"queue": "intel_collect"},
        "tasks.parse_article": {"queue": "intel_parse"},
        "tasks.deduplicate_article": {"queue": "intel_parse"},
        "tasks.enrich_article": {"queue": "intel_enrich"},
        "tasks.enrich_and_match_article": {"queue": "intel_enrich"},
        "tasks.match_article": {"queue": "intel_enrich"},
        "tasks.update_trending_topics": {"queue": "intel_enrich"},
        "tasks.send_alert": {"queue": "intel_notify"},
    },
    beat_schedule={
        "sync-all-mailboxes": {
            "task": "app.agents.email_collector.tasks.sync_all_mailboxes",
            "schedule": crontab(minute="*/5"),
        },
        "poll-intel-sources": {
            "task": "tasks.poll_all_sources",
            "schedule": crontab(minute=0),  # hourly
        },
        "update-trending-topics": {
            "task": "tasks.update_trending_topics",
            "schedule": crontab(hour=3, minute=0),  # 3am daily
        },
    },
)

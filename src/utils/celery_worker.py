from celery import Celery
from celery.schedules import crontab
from src.config import CELERY_BACHUP_RATE, REDIS_HOST, REDIS_PORT

celery_app = Celery(
    "tasks",
    broker=f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
    backend=f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
    include=["src.tasks.backup", "src.tasks.cleanup", "src.tasks.reporting"]
)

celery_app.conf.broker_transport_options = {
    "visibility_timeout": 3600,
    "socket_keepalive": True,
    "retry_on_timeout": True,
    "max_retries": 3
}

celery_app.conf.timezone = "Europe/Kiev"
celery_app.conf.beat_schedule = {
    "backup-every-12-hours": {
        "task": "src.tasks.backup.send_db_backup_task",
        "schedule": crontab(hour='8-21', minute=0),
    },
    "clean-old-logs-daily": {
        "task": "src.tasks.cleanup.clean_old_logs",
        "schedule": crontab(hour=0, minute=0),
    },
    "send-first-half-report": {
        "task": "src.tasks.reporting.send_periodic_reports_task",
        "schedule": crontab(day_of_month="17", hour=6, minute=0),
    },
    "send-second-half-report": {
        "task": "src.tasks.reporting.send_periodic_reports_task",
        "schedule": crontab(day_of_month="3", hour=6, minute=0),
    },
}
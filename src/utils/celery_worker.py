from celery import Celery
from src.config import CELERY_BACHUP_RATE, REDIS_HOST, REDIS_PORT

celery_app = Celery(
    "tasks",
    broker=f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
    backend=f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
    include=["src.tasks.backup", "src.tasks.cleanup"]
)

celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "backup-every-12-hours": {
        "task": "src.tasks.backup.send_db_backup_task",
        "schedule": CELERY_BACHUP_RATE,  # 12 hours in seconds
    },
    "clean-old-logs-daily": {
        "task": "src.tasks.cleanup.clean_old_logs",
        "schedule": 86400, # 24 hours in seconds
    },
}
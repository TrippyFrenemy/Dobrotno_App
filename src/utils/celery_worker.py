from celery import Celery
from src.config import CELERY_BACHUP_RATE, REDIS_HOST, REDIS_PORT

celery_app = Celery(
    "tasks",
    broker=f"redis://{REDIS_HOST}:{REDIS_PORT}/0",
    backend=f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
    include=["src.tasks.backup"]
)

celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "backup-every-1-minute": {
        "task": "src.tasks.backup.send_db_backup_task",
        "schedule": CELERY_BACHUP_RATE,  # 1 минута
    }
}
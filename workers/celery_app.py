import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery = Celery("arena", broker=redis_url, backend=redis_url)
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery.conf.beat_schedule = {
    "due-schedules-every-minute": {
        "task": "workers.tasks.run_due_schedules",
        "schedule": 60.0,
    }
}
celery.autodiscover_tasks(["workers"])


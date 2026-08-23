from datetime import datetime
from workers.celery_app import celery


def _app():
    from app import create_app
    return create_app()


@celery.task(bind=True, max_retries=3, name="workers.tasks.run_step")
def run_step(self, project_id: int, step: str):
    app = _app()
    with app.app_context():
        from app.services import pipeline as p
        mapping = {
            "analyze": p.analyze_project,
            "transcribe": p.transcribe_project,
            "script": p.generate_script,
            "voice": p.generate_voice,
            "subtitle": p.generate_subtitle,
            "render": p.render_video,
            "thumbnail": p.generate_thumbnail,
            "metadata": p.generate_metadata,
            "quality": p.quality_check,
            "full": p.run_full_pipeline,
        }
        fn = mapping.get(step)
        if not fn:
            raise ValueError(step)
        try:
            return {"ok": True, "result": str(fn(project_id))}
        except Exception as exc:
            raise self.retry(exc=exc, countdown=15)


@celery.task(name="workers.tasks.run_due_schedules")
def run_due_schedules():
    app = _app()
    with app.app_context():
        from app.extensions import db
        from app.models.content import AutomationSchedule, VideoProject
        now = datetime.utcnow()
        for sch in AutomationSchedule.query.filter_by(enabled=True).all():
            if sch.hour is None:
                continue
            if now.hour == sch.hour and (sch.minute or 0) == now.minute:
                if sch.weekday:
                    names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                    if names[now.weekday()] not in sch.weekday.lower():
                        continue
                proj = VideoProject.query.filter_by(status="READY", is_deleted=False).first()
                if proj:
                    run_step.delay(proj.id, "full")
                    sch.last_run_at = now
                    db.session.commit()

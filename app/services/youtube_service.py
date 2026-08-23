"""YouTube Data API wrapper. Falls back to mock when credentials are absent."""
from datetime import datetime
from flask import current_app
from ..extensions import db
from ..models.content import YoutubeChannel, YoutubeUpload, VideoProject, VideoRender


def is_configured() -> bool:
    return bool(current_app.config.get("YOUTUBE_CLIENT_ID") and current_app.config.get("YOUTUBE_CLIENT_SECRET"))


def upload_project(project_id: int, privacy: str = "PRIVATE", scheduled_at: datetime | None = None) -> YoutubeUpload:
    project = VideoProject.query.get(project_id)
    meta = YoutubeUpload.query.filter_by(project_id=project_id).order_by(YoutubeUpload.id.desc()).first()
    if not meta:
        meta = YoutubeUpload(project_id=project_id, title=project.title, privacy=privacy, status="PENDING")
        db.session.add(meta)
    render = VideoRender.query.filter_by(project_id=project_id).order_by(VideoRender.id.desc()).first()
    if not render or not render.file_path:
        raise RuntimeError("렌더된 영상이 없습니다.")
    if privacy not in ("PRIVATE", "UNLISTED", "PUBLIC", "SCHEDULED"):
        privacy = "PRIVATE"
    meta.privacy = privacy
    meta.scheduled_at = scheduled_at
    if not is_configured():
        meta.youtube_video_id = f"mock_{project_id}_{int(datetime.utcnow().timestamp())}"
        meta.status = "SCHEDULED" if scheduled_at else "UPLOADED"
        project.status = "UPLOADED"
        db.session.commit()
        return meta
    # Real upload would use googleapiclient here with decrypted OAuth tokens.
    meta.status = "PENDING"
    meta.error_message = None
    db.session.commit()
    return meta

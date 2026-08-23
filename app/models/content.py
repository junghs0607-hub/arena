from datetime import datetime
from ..extensions import db


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VideoSource(db.Model, TimestampMixin):
    __tablename__ = "video_sources"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(500), nullable=False)
    origin_url = db.Column(db.String(2000))
    source_type = db.Column(db.String(32), default="upload")  # upload | url
    file_path = db.Column(db.String(1000))
    creator = db.Column(db.String(255))
    category = db.Column(db.String(120))
    tags = db.Column(db.String(500))
    notes = db.Column(db.Text)
    copyright_status = db.Column(db.String(64), default="unconfirmed")
    license_name = db.Column(db.String(255))
    rights_owner = db.Column(db.Boolean, default=False)
    reuse_permitted = db.Column(db.Boolean, default=False)
    reusable_license = db.Column(db.Boolean, default=False)
    public_domain = db.Column(db.Boolean, default=False)
    rights_confirmed = db.Column(db.Boolean, default=False, index=True)
    duration_sec = db.Column(db.Float)
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    status = db.Column(db.String(32), default="READY", index=True)
    error_message = db.Column(db.Text)
    is_deleted = db.Column(db.Boolean, default=False, index=True)

    licenses = db.relationship("SourceLicense", backref="source", lazy=True)
    projects = db.relationship("VideoProject", backref="source", lazy=True)


class SourceLicense(db.Model, TimestampMixin):
    __tablename__ = "source_licenses"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("video_sources.id"), nullable=False, index=True)
    claim_type = db.Column(db.String(64), nullable=False)
    confirmed = db.Column(db.Boolean, default=False)
    notes = db.Column(db.Text)


class VideoProject(db.Model, TimestampMixin):
    __tablename__ = "video_projects"

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey("video_sources.id"), nullable=False, index=True)
    title = db.Column(db.String(500), nullable=False)
    format_type = db.Column(db.String(32), default="shorts")  # shorts | longform
    target_duration = db.Column(db.Integer, default=60)
    language = db.Column(db.String(16), default="ko")
    status = db.Column(db.String(32), default="READY", index=True)
    analysis_json = db.Column(db.Text)
    quality_json = db.Column(db.Text)
    error_message = db.Column(db.Text)
    automation_mode = db.Column(db.String(32), default="semi")  # auto | semi | manual
    is_deleted = db.Column(db.Boolean, default=False, index=True)

    scenes = db.relationship("VideoScene", backref="project", lazy=True)
    transcripts = db.relationship("Transcript", backref="project", lazy=True)
    scripts = db.relationship("Script", backref="project", lazy=True)
    voices = db.relationship("VoiceGeneration", backref="project", lazy=True)
    subtitles = db.relationship("Subtitle", backref="project", lazy=True)
    renders = db.relationship("VideoRender", backref="project", lazy=True)
    thumbs = db.relationship("Thumbnail", backref="project", lazy=True)


class VideoScene(db.Model, TimestampMixin):
    __tablename__ = "video_scenes"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), nullable=False, index=True)
    index = db.Column(db.Integer, default=0)
    start_sec = db.Column(db.Float, default=0)
    end_sec = db.Column(db.Float, default=0)
    label = db.Column(db.String(120))
    description = db.Column(db.Text)
    importance = db.Column(db.Float, default=0.5)
    keep = db.Column(db.Boolean, default=True)


class Transcript(db.Model, TimestampMixin):
    __tablename__ = "transcripts"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), nullable=False, index=True)
    language = db.Column(db.String(16), default="ko")
    text = db.Column(db.Text)
    provider = db.Column(db.String(64), default="mock")
    cache_key = db.Column(db.String(128), index=True)
    status = db.Column(db.String(32), default="READY")
    error_message = db.Column(db.Text)


class Script(db.Model, TimestampMixin):
    __tablename__ = "scripts"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), nullable=False, index=True)
    format_type = db.Column(db.String(32), default="shorts")
    body = db.Column(db.Text)
    hook = db.Column(db.Text)
    conclusion = db.Column(db.Text)
    provider = db.Column(db.String(64), default="mock")
    status = db.Column(db.String(32), default="READY")
    error_message = db.Column(db.Text)
    versions = db.relationship("ScriptVersion", backref="script", lazy=True)


class ScriptVersion(db.Model, TimestampMixin):
    __tablename__ = "script_versions"

    id = db.Column(db.Integer, primary_key=True)
    script_id = db.Column(db.Integer, db.ForeignKey("scripts.id"), nullable=False, index=True)
    body = db.Column(db.Text)
    note = db.Column(db.String(255))


class VoiceGeneration(db.Model, TimestampMixin):
    __tablename__ = "voice_generations"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), nullable=False, index=True)
    file_path = db.Column(db.String(1000))
    provider = db.Column(db.String(64), default="mock")
    voice_style = db.Column(db.String(64), default="friendly")
    language = db.Column(db.String(16), default="ko")
    gender = db.Column(db.String(16), default="feminine")
    cache_key = db.Column(db.String(128), index=True)
    status = db.Column(db.String(32), default="READY")
    error_message = db.Column(db.Text)


class Subtitle(db.Model, TimestampMixin):
    __tablename__ = "subtitles"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), nullable=False, index=True)
    format = db.Column(db.String(16), default="srt")
    file_path = db.Column(db.String(1000))
    content = db.Column(db.Text)
    word_highlight = db.Column(db.Boolean, default=True)
    status = db.Column(db.String(32), default="READY")
    error_message = db.Column(db.Text)


class AudioTrack(db.Model, TimestampMixin):
    __tablename__ = "audio_tracks"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), index=True)
    kind = db.Column(db.String(32), default="bgm")  # bgm | sfx | narration
    file_path = db.Column(db.String(1000))
    volume = db.Column(db.Float, default=0.3)


class VideoRender(db.Model, TimestampMixin):
    __tablename__ = "video_renders"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), nullable=False, index=True)
    file_path = db.Column(db.String(1000))
    aspect = db.Column(db.String(16), default="9:16")
    width = db.Column(db.Integer)
    height = db.Column(db.Integer)
    duration_sec = db.Column(db.Float)
    progress = db.Column(db.Integer, default=0)
    status = db.Column(db.String(32), default="PENDING", index=True)
    error_message = db.Column(db.Text)


class Thumbnail(db.Model, TimestampMixin):
    __tablename__ = "thumbnails"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), nullable=False, index=True)
    file_path = db.Column(db.String(1000))
    headline = db.Column(db.String(255))
    subheadline = db.Column(db.String(255))
    status = db.Column(db.String(32), default="READY")
    error_message = db.Column(db.Text)


class YoutubeChannel(db.Model, TimestampMixin):
    __tablename__ = "youtube_channels"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255))
    channel_id = db.Column(db.String(128), index=True)
    token_encrypted = db.Column(db.Text)
    refresh_encrypted = db.Column(db.Text)
    status = db.Column(db.String(32), default="disconnected")


class YoutubeUpload(db.Model, TimestampMixin):
    __tablename__ = "youtube_uploads"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), index=True)
    channel_id = db.Column(db.Integer, db.ForeignKey("youtube_channels.id"), index=True)
    youtube_video_id = db.Column(db.String(64), index=True)
    title = db.Column(db.String(500))
    description = db.Column(db.Text)
    tags = db.Column(db.String(1000))
    hashtags = db.Column(db.String(500))
    category = db.Column(db.String(64))
    chapters = db.Column(db.Text)
    pinned_comment = db.Column(db.Text)
    privacy = db.Column(db.String(32), default="PRIVATE")
    scheduled_at = db.Column(db.DateTime)
    status = db.Column(db.String(32), default="PENDING", index=True)
    error_message = db.Column(db.Text)
    click_score = db.Column(db.Float)


class YoutubeStatistic(db.Model, TimestampMixin):
    __tablename__ = "youtube_statistics"

    id = db.Column(db.Integer, primary_key=True)
    upload_id = db.Column(db.Integer, db.ForeignKey("youtube_uploads.id"), index=True)
    views = db.Column(db.Integer, default=0)
    likes = db.Column(db.Integer, default=0)
    comments = db.Column(db.Integer, default=0)
    subscribers_gained = db.Column(db.Integer, default=0)


class AutomationJob(db.Model, TimestampMixin):
    __tablename__ = "automation_jobs"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("video_projects.id"), index=True)
    task = db.Column(db.String(64), index=True)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    status = db.Column(db.String(32), default="PENDING", index=True)
    error_message = db.Column(db.Text)
    retry_count = db.Column(db.Integer, default=0)
    celery_id = db.Column(db.String(128))


class AutomationSchedule(db.Model, TimestampMixin):
    __tablename__ = "automation_schedules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    cron_like = db.Column(db.String(64))  # e.g. daily 10:00
    weekday = db.Column(db.String(32))
    hour = db.Column(db.Integer)
    minute = db.Column(db.Integer)
    enabled = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    status = db.Column(db.String(32), default="READY")


class AiProvider(db.Model, TimestampMixin):
    __tablename__ = "ai_providers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), unique=True)
    kind = db.Column(db.String(32))  # llm | tts | stt
    base_url = db.Column(db.String(500))
    model = db.Column(db.String(120))
    enabled = db.Column(db.Boolean, default=True)
    is_default = db.Column(db.Boolean, default=False)


class SystemSetting(db.Model, TimestampMixin):
    __tablename__ = "system_settings"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(128), unique=True, index=True)
    value = db.Column(db.Text)


class ContentCache(db.Model, TimestampMixin):
    __tablename__ = "content_cache"

    id = db.Column(db.Integer, primary_key=True)
    cache_key = db.Column(db.String(128), unique=True, index=True)
    kind = db.Column(db.String(32), index=True)
    payload = db.Column(db.Text)

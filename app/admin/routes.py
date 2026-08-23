from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func
from ..models.content import VideoProject, YoutubeUpload, YoutubeStatistic, AutomationJob, VideoSource

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/")
@login_required
def dashboard():
    q = VideoProject.query.filter_by(is_deleted=False)
    counts = {
        "today": q.filter(VideoProject.status.in_(["READY_TO_UPLOAD", "UPLOADED", "REVIEW", "EDITING"])).count(),
        "in_progress": q.filter(VideoProject.status.in_(["ANALYZING", "SCRIPTING", "VOICE_GENERATING", "EDITING"])).count(),
        "review": q.filter_by(status="REVIEW").count(),
        "uploaded": q.filter_by(status="UPLOADED").count(),
        "failed": q.filter_by(status="FAILED").count(),
        "scheduled": YoutubeUpload.query.filter_by(status="SCHEDULED").count(),
        "sources": VideoSource.query.filter_by(is_deleted=False).count(),
    }
    stats = YoutubeStatistic.query.with_entities(
        func.coalesce(func.sum(YoutubeStatistic.views), 0),
        func.coalesce(func.avg(YoutubeStatistic.views), 0),
        func.coalesce(func.sum(YoutubeStatistic.likes), 0),
        func.coalesce(func.sum(YoutubeStatistic.comments), 0),
        func.coalesce(func.sum(YoutubeStatistic.subscribers_gained), 0),
    ).first()
    counts["views"] = int(stats[0] or 0)
    counts["avg_views"] = int(stats[1] or 0)
    counts["likes"] = int(stats[2] or 0)
    counts["comments"] = int(stats[3] or 0)
    counts["subs"] = int(stats[4] or 0)
    jobs = AutomationJob.query.order_by(AutomationJob.id.desc()).limit(12).all()
    projects = q.order_by(VideoProject.id.desc()).limit(8).all()
    return render_template("admin/dashboard.html", counts=counts, jobs=jobs, projects=projects)

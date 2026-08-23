from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from ..extensions import db
from ..models.content import YoutubeChannel, YoutubeUpload, YoutubeStatistic, AutomationSchedule, VideoProject
from ..services.youtube_service import upload_project, is_configured

youtube_bp = Blueprint("youtube", __name__, url_prefix="/youtube")


@youtube_bp.route("/channels")
@login_required
def channels():
    items = YoutubeChannel.query.all()
    return render_template("youtube/channels.html", items=items, configured=is_configured())


@youtube_bp.route("/uploads")
@login_required
def uploads():
    items = YoutubeUpload.query.order_by(YoutubeUpload.id.desc()).all()
    return render_template("youtube/uploads.html", items=items)


@youtube_bp.route("/schedule", methods=["GET", "POST"])
@login_required
def schedule():
    if request.method == "POST":
        sch = AutomationSchedule(
            name=request.form.get("name") or "slot",
            cron_like=request.form.get("cron_like") or "",
            weekday=request.form.get("weekday") or "",
            hour=int(request.form.get("hour") or 10),
            minute=int(request.form.get("minute") or 0),
            enabled=True,
        )
        db.session.add(sch)
        db.session.commit()
        flash("스케줄이 저장되었습니다.", "success")
        return redirect(url_for("youtube.schedule"))
    items = AutomationSchedule.query.order_by(AutomationSchedule.id.desc()).all()
    return render_template("youtube/schedule.html", items=items)


@youtube_bp.route("/upload/<int:pid>", methods=["POST"])
@login_required
def do_upload(pid):
    privacy = request.form.get("privacy") or "PRIVATE"
    scheduled = request.form.get("scheduled_at")
    dt = datetime.fromisoformat(scheduled) if scheduled else None
    try:
        upload_project(pid, privacy=privacy, scheduled_at=dt)
        flash("업로드(또는 모의 업로드)가 완료되었습니다.", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("projects.detail", pid=pid))


@youtube_bp.route("/stats")
@login_required
def stats():
    items = YoutubeStatistic.query.order_by(YoutubeStatistic.id.desc()).limit(50).all()
    if not items:
        # seed mock stat for demo visibility
        up = YoutubeUpload.query.filter_by(status="UPLOADED").first()
        if up:
            s = YoutubeStatistic(upload_id=up.id, views=1200, likes=80, comments=12, subscribers_gained=3)
            db.session.add(s)
            db.session.commit()
            items = [s]
    return render_template("youtube/stats.html", items=items)

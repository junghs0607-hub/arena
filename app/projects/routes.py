import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
from flask_login import login_required
from ..extensions import db
from ..models.content import (
    VideoProject,
    VideoSource,
    Transcript,
    Script,
    VoiceGeneration,
    Subtitle,
    VideoRender,
    Thumbnail,
    YoutubeUpload,
    AutomationJob,
    VideoScene,
)
from ..services import pipeline as pipe

projects_bp = Blueprint("projects", __name__, url_prefix="/projects")


@projects_bp.route("/")
@login_required
def list_projects():
    fmt = request.args.get("format")
    trash = request.args.get("trash") == "1"
    q = VideoProject.query.filter_by(is_deleted=trash)
    if fmt in ("shorts", "longform"):
        q = q.filter_by(format_type=fmt)
    items = q.order_by(VideoProject.id.desc()).all()
    return render_template("projects/list.html", items=items, fmt=fmt, trash=trash)


@projects_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_project():
    sources = VideoSource.query.filter_by(is_deleted=False).order_by(VideoSource.id.desc()).all()
    if request.method == "POST":
        src = VideoSource.query.get(int(request.form["source_id"]))
        if not src.rights_confirmed:
            flash("권리 확인이 되지 않은 소스는 프로젝트를 생성할 수 없습니다.", "danger")
            return redirect(url_for("projects.new_project"))
        p = VideoProject(
            source_id=src.id,
            title=request.form.get("title") or src.title,
            format_type=request.form.get("format_type") or "shorts",
            target_duration=int(request.form.get("target_duration") or 60),
            language=request.form.get("language") or "ko",
            automation_mode=request.form.get("automation_mode") or "semi",
            status="READY",
        )
        db.session.add(p)
        db.session.commit()
        if p.automation_mode == "auto":
            try:
                pipe.run_full_pipeline(p.id)
                flash("자동 파이프라인이 완료되었습니다.", "success")
            except Exception as exc:
                flash(f"파이프라인 오류: {exc}", "danger")
        return redirect(url_for("projects.detail", pid=p.id))
    return render_template("projects/form.html", sources=sources)


@projects_bp.route("/<int:pid>")
@login_required
def detail(pid):
    p = VideoProject.query.get_or_404(pid)
    ctx = {
        "p": p,
        "transcript": Transcript.query.filter_by(project_id=pid).order_by(Transcript.id.desc()).first(),
        "script": Script.query.filter_by(project_id=pid).order_by(Script.id.desc()).first(),
        "voice": VoiceGeneration.query.filter_by(project_id=pid).order_by(VoiceGeneration.id.desc()).first(),
        "subtitle": Subtitle.query.filter_by(project_id=pid).order_by(Subtitle.id.desc()).first(),
        "render": VideoRender.query.filter_by(project_id=pid).order_by(VideoRender.id.desc()).first(),
        "thumb": Thumbnail.query.filter_by(project_id=pid).order_by(Thumbnail.id.desc()).first(),
        "meta": YoutubeUpload.query.filter_by(project_id=pid).order_by(YoutubeUpload.id.desc()).first(),
        "jobs": AutomationJob.query.filter_by(project_id=pid).order_by(AutomationJob.id.desc()).limit(20).all(),
        "scenes": VideoScene.query.filter_by(project_id=pid).order_by(VideoScene.index).all(),
    }
    return render_template("projects/detail.html", **ctx)


@projects_bp.route("/<int:pid>/run/<step>", methods=["POST"])
@login_required
def run_step(pid, step):
    mapping = {
        "analyze": pipe.analyze_project,
        "transcribe": pipe.transcribe_project,
        "script": pipe.generate_script,
        "voice": pipe.generate_voice,
        "subtitle": pipe.generate_subtitle,
        "render": pipe.render_video,
        "thumbnail": pipe.generate_thumbnail,
        "metadata": pipe.generate_metadata,
        "quality": pipe.quality_check,
        "full": pipe.run_full_pipeline,
    }
    fn = mapping.get(step)
    if not fn:
        abort(404)
    try:
        use_celery = request.form.get("celery") == "1"
        if use_celery:
            from workers.tasks import run_step as celery_step
            celery_step.delay(pid, step)
            flash("백그라운드 작업이 큐에 등록되었습니다.", "info")
        else:
            fn(pid)
            flash(f"{step} 완료", "success")
    except Exception as exc:
        flash(str(exc), "danger")
    return redirect(url_for("projects.detail", pid=pid))


@projects_bp.route("/<int:pid>/script", methods=["POST"])
@login_required
def edit_script(pid):
    s = Script.query.filter_by(project_id=pid).order_by(Script.id.desc()).first_or_404()
    s.body = request.form.get("body") or s.body
    db.session.commit()
    flash("대본이 저장되었습니다.", "success")
    return redirect(url_for("projects.detail", pid=pid))


@projects_bp.route("/<int:pid>/media/<kind>")
@login_required
def media(pid, kind):
    if kind == "render":
        row = VideoRender.query.filter_by(project_id=pid).order_by(VideoRender.id.desc()).first_or_404()
    elif kind == "thumb":
        row = Thumbnail.query.filter_by(project_id=pid).order_by(Thumbnail.id.desc()).first_or_404()
    elif kind == "voice":
        row = VoiceGeneration.query.filter_by(project_id=pid).order_by(VoiceGeneration.id.desc()).first_or_404()
    else:
        abort(404)
    if not row.file_path or not os.path.isfile(row.file_path):
        abort(404)
    return send_file(row.file_path)


@projects_bp.route("/<int:pid>/delete", methods=["POST"])
@login_required
def delete_project(pid):
    p = VideoProject.query.get_or_404(pid)
    p.is_deleted = True
    db.session.commit()
    return redirect(url_for("projects.list_projects"))

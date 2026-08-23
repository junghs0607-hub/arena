from flask import Blueprint, jsonify, request, abort
from flask_login import login_required
from ..extensions import db, csrf
from ..models.content import VideoSource, VideoProject, YoutubeUpload
from ..services import pipeline as pipe

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/sources")
@login_required
def sources():
    items = VideoSource.query.filter_by(is_deleted=False).all()
    return jsonify([{"id": s.id, "title": s.title, "status": s.status, "rights": s.rights_confirmed} for s in items])


@api_bp.route("/sources/<int:sid>")
@login_required
def source_one(sid):
    s = VideoSource.query.get_or_404(sid)
    return jsonify({"id": s.id, "title": s.title, "url": s.origin_url, "rights": s.rights_confirmed})


@api_bp.route("/projects")
@login_required
def projects():
    items = VideoProject.query.filter_by(is_deleted=False).all()
    return jsonify([{"id": p.id, "title": p.title, "status": p.status, "format": p.format_type} for p in items])


@api_bp.route("/projects/<int:pid>")
@login_required
def project_one(pid):
    p = VideoProject.query.get_or_404(pid)
    return jsonify({"id": p.id, "title": p.title, "status": p.status, "error": p.error_message})


@api_bp.route("/projects/<int:pid>/<action>", methods=["POST"])
@login_required
@csrf.exempt
def project_action(pid, action):
    mapping = {
        "analyze": pipe.analyze_project,
        "generate-script": pipe.generate_script,
        "generate-voice": pipe.generate_voice,
        "generate-subtitle": pipe.generate_subtitle,
        "render": pipe.render_video,
    }
    fn = mapping.get(action)
    if not fn:
        abort(404)
    try:
        fn(pid)
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@api_bp.route("/youtube/uploads")
@login_required
def yt_uploads():
    items = YoutubeUpload.query.order_by(YoutubeUpload.id.desc()).all()
    return jsonify([{"id": u.id, "title": u.title, "status": u.status} for u in items])


@api_bp.route("/analytics")
@login_required
def analytics():
    return jsonify({"projects": VideoProject.query.count(), "sources": VideoSource.query.count()})

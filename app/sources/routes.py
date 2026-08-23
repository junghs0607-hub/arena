from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from ..extensions import db
from ..models.content import VideoSource, SourceLicense
from ..utils.files import safe_save
from ..services.ffmpeg_service import probe

sources_bp = Blueprint("sources", __name__, url_prefix="/sources")


def _rights_ok(form) -> bool:
    return any(
        form.get(k)
        for k in ("rights_owner", "reuse_permitted", "reusable_license", "public_domain")
    )


@sources_bp.route("/")
@login_required
def list_sources():
    trash = request.args.get("trash") == "1"
    items = VideoSource.query.filter_by(is_deleted=trash).order_by(VideoSource.id.desc()).all()
    return render_template("sources/list.html", items=items, trash=trash)


@sources_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_source():
    if request.method == "POST":
        rights = _rights_ok(request.form)
        src = VideoSource(
            title=request.form.get("title") or "Untitled",
            origin_url=request.form.get("origin_url") or None,
            source_type="upload" if request.files.get("file") and request.files["file"].filename else "url",
            creator=request.form.get("creator"),
            category=request.form.get("category"),
            tags=request.form.get("tags"),
            notes=request.form.get("notes"),
            license_name=request.form.get("license_name"),
            rights_owner=bool(request.form.get("rights_owner")),
            reuse_permitted=bool(request.form.get("reuse_permitted")),
            reusable_license=bool(request.form.get("reusable_license")),
            public_domain=bool(request.form.get("public_domain")),
            rights_confirmed=rights,
            copyright_status="confirmed" if rights else "unconfirmed",
            status="READY",
        )
        f = request.files.get("file")
        if f and f.filename:
            path = safe_save(f, "source", current_app.config["ALLOWED_VIDEO_EXTENSIONS"])
            src.file_path = path
            meta = probe(path)
            src.duration_sec = meta.get("duration")
            src.width = meta.get("width")
            src.height = meta.get("height")
        if src.source_type == "url" and src.origin_url and not src.file_path:
            # Do not download third-party videos automatically.
            src.notes = (src.notes or "") + "\n[참고] URL은 출처 기록용입니다. 보호된 콘텐츠는 다운로드하지 않습니다. 파일을 직접 업로드하세요."
        db.session.add(src)
        db.session.flush()
        for key, label in (
            ("rights_owner", "저작권 보유"),
            ("reuse_permitted", "재사용 허가"),
            ("reusable_license", "재사용 라이선스"),
            ("public_domain", "퍼블릭 도메인"),
        ):
            if request.form.get(key):
                db.session.add(SourceLicense(source_id=src.id, claim_type=label, confirmed=True))
        db.session.commit()
        flash("소스가 등록되었습니다." + ("" if rights else " 권리 확인 전에는 자동 제작이 제한됩니다."), "success" if rights else "warning")
        return redirect(url_for("sources.list_sources"))
    return render_template("sources/form.html")


@sources_bp.route("/<int:sid>/delete", methods=["POST"])
@login_required
def delete_source(sid):
    src = VideoSource.query.get_or_404(sid)
    src.is_deleted = True
    db.session.commit()
    return redirect(url_for("sources.list_sources"))

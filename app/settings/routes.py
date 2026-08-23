from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required
from ..extensions import db
from ..models.content import AiProvider, SystemSetting, AutomationJob

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


@settings_bp.route("/", methods=["GET", "POST"])
@login_required
def index():
    if request.method == "POST":
        for key in ("automation_mode", "default_language"):
            val = request.form.get(key)
            if val is None:
                continue
            row = SystemSetting.query.filter_by(key=key).first()
            if row:
                row.value = val
            else:
                db.session.add(SystemSetting(key=key, value=val))
        db.session.commit()
        flash("설정이 저장되었습니다. API 키는 환경변수(.env)로만 관리됩니다.", "success")
        return redirect(url_for("settings.index"))
    settings = {s.key: s.value for s in SystemSetting.query.all()}
    providers = AiProvider.query.all()
    jobs = AutomationJob.query.order_by(AutomationJob.id.desc()).limit(30).all()
    return render_template(
        "settings/index.html",
        settings=settings,
        providers=providers,
        jobs=jobs,
        cfg=current_app.config,
    )

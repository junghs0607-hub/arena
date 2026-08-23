import os
from flask import Flask
from .config import Config
from .extensions import db, login_manager, migrate, csrf, limiter


def create_app(config_class=Config):
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(config_class)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    for sub in ("source", "audio", "subtitles", "thumbnails", "render", "final"):
        os.makedirs(os.path.join(app.config["UPLOAD_FOLDER"], sub), exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from .models import user as _user  # noqa: F401
    from .models import content  # noqa: F401

    from .auth.routes import auth_bp
    from .admin.routes import admin_bp
    from .sources.routes import sources_bp
    from .projects.routes import projects_bp
    from .youtube.routes import youtube_bp
    from .settings.routes import settings_bp
    from .api.routes import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(sources_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(youtube_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)

    with app.app_context():
        db.create_all()
        from .utils.seed import seed_admin
        seed_admin()

    return app

from flask import current_app
from ..extensions import db
from ..models.user import User
from ..models.content import AiProvider, SystemSetting


def seed_admin():
    email = current_app.config["ADMIN_EMAIL"]
    if not User.query.filter_by(email=email).first():
        u = User(email=email, name="Administrator", role="admin")
        u.set_password(current_app.config["ADMIN_PASSWORD"])
        db.session.add(u)
    if not AiProvider.query.filter_by(name="mock-llm").first():
        db.session.add(AiProvider(name="mock-llm", kind="llm", model="mock", enabled=True, is_default=True))
        db.session.add(AiProvider(name="mock-tts", kind="tts", model="mock", enabled=True, is_default=True))
        db.session.add(AiProvider(name="mock-stt", kind="stt", model="mock", enabled=True, is_default=True))
    if not SystemSetting.query.filter_by(key="automation_mode").first():
        db.session.add(SystemSetting(key="automation_mode", value="semi"))
    db.session.commit()

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "로그인이 필요합니다."
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])


@login_manager.user_loader
def load_user(user_id):
    from .models.user import User
    return User.query.get(int(user_id))

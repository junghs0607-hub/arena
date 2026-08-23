import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///arena.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.abspath(os.getenv("UPLOAD_FOLDER", "storage"))
    MAX_CONTENT_LENGTH = int(os.getenv("MAX_CONTENT_LENGTH", 524288000))
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    WTF_CSRF_ENABLED = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin1234")
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
    LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    LLM_API_KEY = os.getenv("LLM_API_KEY", "")
    LLM_MODEL = os.getenv("LLM_MODEL", "llama3")
    TTS_PROVIDER = os.getenv("TTS_PROVIDER", "mock")
    STT_PROVIDER = os.getenv("STT_PROVIDER", "mock")
    YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "")
    YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "")
    YOUTUBE_REDIRECT_URI = os.getenv("YOUTUBE_REDIRECT_URI", "")
    FERNET_KEY = os.getenv("FERNET_KEY", "")
    ALLOWED_VIDEO_EXTENSIONS = {"mp4", "mov", "mkv", "webm", "avi"}
    ALLOWED_AUDIO_EXTENSIONS = {"mp3", "wav", "m4a", "aac", "ogg"}

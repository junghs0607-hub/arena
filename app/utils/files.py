import os
import uuid
from werkzeug.utils import secure_filename
from flask import current_app


def allowed_file(filename: str, allowed: set) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed


def safe_save(file_storage, subdir: str, allowed: set) -> str:
    filename = secure_filename(file_storage.filename or "")
    if not filename or not allowed_file(filename, allowed):
        raise ValueError("허용되지 않은 파일 형식입니다.")
    ext = filename.rsplit(".", 1)[1].lower()
    name = f"{uuid.uuid4().hex}.{ext}"
    dest_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], subdir)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.abspath(os.path.join(dest_dir, name))
    root = os.path.abspath(dest_dir)
    if not dest.startswith(root):
        raise ValueError("잘못된 경로입니다.")
    file_storage.save(dest)
    return dest

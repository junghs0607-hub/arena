import os
from cryptography.fernet import Fernet
from flask import current_app


def _fernet() -> Fernet:
    key = current_app.config.get("FERNET_KEY") or os.getenv("FERNET_KEY")
    if not key:
        # ephemeral fallback for local mock only
        key = Fernet.generate_key().decode()
        current_app.config["FERNET_KEY"] = key
    if isinstance(key, str):
        key = key.encode()
    return Fernet(key)


def encrypt_str(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(value: str) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value.encode()).decode()

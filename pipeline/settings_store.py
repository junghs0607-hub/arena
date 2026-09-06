"""SQLite 설정 스토어: 스튜디오 설정 + 관리자 계정을 DB 파일 하나로 관리.

- 기본 DB 경로: ``data/settings.db`` (gitignore 처리 — 이관 시 파일 하나만 복사하면 끝)
- 값은 모두 JSON으로 저장 (`set`/`get`이 자동 직렬화)
- 비밀번호: PBKDF2-HMAC-SHA256(20만 회) + 16바이트 랜덤 솔트, 비교는 hmac.compare_digest
- 파일 기반 설정(admin/*.json, 템플릿 txt)은 계속 동작하고, DB에 같은 키가 있으면 DB가 우선
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

DEFAULT_DB = Path("data/settings.db")

_PBKDF2_ROUNDS = 200_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS admins (
    username TEXT PRIMARY KEY,
    pass_hash TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


def _connect(db_path: Path | str) -> sqlite3.Connection:
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def get(db_path: Path | str, key: str, default=None):
    """키 조회. 값은 JSON 직렬화가 풀린 파이썬 객체."""
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except Exception:  # noqa: BLE001
        return default


def set(db_path: Path | str, key: str, value) -> None:
    blob = json.dumps(value, ensure_ascii=False)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, blob, time.time()),
        )


def delete(db_path: Path | str, key: str) -> None:
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


def get_section(db_path: Path | str, prefix: str) -> dict:
    """`prefix.*` 키를 섹션 dict로 묶어 반환 (기본값 병합용)."""
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM settings WHERE key LIKE ?", (prefix + ".%",)).fetchall()
    out: dict = {}
    for r in rows:
        try:
            out[r["key"][len(prefix) + 1:]] = json.loads(r["value"])
        except Exception:  # noqa: BLE001
            continue
    return out


def get_or_create_secret(db_path: Path | str, key: str = "flask.secret_key") -> str:
    """Flask 세션 시크릿: DB에 영구 보관(재시작필요 로그아웃 방지)."""
    v = get(db_path, key)
    if isinstance(v, str) and len(v) >= 32:
        return v
    v = secrets.token_hex(32)
    set(db_path, key, v)
    return v


def _hash_password(password: str, salt_hex: str, rounds: int = _PBKDF2_ROUNDS) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), rounds
    )
    return f"pbkdf2${rounds}${salt_hex}${digest.hex()}"


def admin_count(db_path: Path | str) -> int:
    with _connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0])


def create_admin(db_path: Path | str, username: str, password: str) -> None:
    if not username.strip():
        raise ValueError("사용자 이름이 비어 있습니다.")
    if len(password) < 6:
        raise ValueError("비밀번호는 6자 이상이어야 합니다.")
    salt = os.urandom(16).hex()
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO admins(username, pass_hash, created_at) VALUES(?, ?, ?) "
            "ON CONFLICT(username) DO UPDATE SET pass_hash=excluded.pass_hash",
            (username.strip(), _hash_password(password, salt), time.time()),
        )


def verify_admin(db_path: Path | str, username: str, password: str) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT pass_hash FROM admins WHERE username = ?", (username.strip(),)
        ).fetchone()
    if row is None:
        return False
    try:
        scheme, rounds, salt, digest = row["pass_hash"].split("$")
        if scheme != "pbkdf2":
            return False
        expect = _hash_password(password, salt, int(rounds)).split("$")[-1]
        return hmac.compare_digest(expect, digest)
    except (ValueError, TypeError):
        return False


def change_password(db_path: Path | str, username: str, new_password: str) -> None:
    create_admin(db_path, username, new_password)  # upsert + 규칙 검증 재사용

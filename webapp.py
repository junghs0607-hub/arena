#!/usr/bin/env python3
"""반자동 쇼츠 조립 시스템 — Flask 웹 UI.

대본을 붙여 넣고(미디어 파일 업로드 선택) [영상 생성]을 누르면
백그라운드 워커가 build.py 파이프라인을 단계별로 실행하고,
완성된 영상을 브라우저에서 바로 다운로드할 수 있다.

실행:
  python webapp.py --host 0.0.0.0 --port 5000

※ 개인/팀 납품용 도구 기준. 인증 없이 공개 인터넷에 노출하지 마세요.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for

from pipeline import scriptgen  # AI 대본 생성(관리자 프롬프트)
from pipeline import settings_store as settings_db  # SQLite 설정/관리자 스토어

ROOT = Path(__file__).resolve().parent
JOBS_ROOT = ROOT / "jobs"
DATA_DIR = ROOT / "data"
ADMIN_PROMPT = ROOT / "admin" / "script_prompt.txt"
ADMIN_PACK_PROMPT = ROOT / "admin" / "scene_pack_prompt.txt"
ADMIN_MEDIA_PROMPT = ROOT / "admin" / "media_prompt.txt"
ADMIN_DOC_PROMPT = ROOT / "admin" / "youtube_doc_prompt.txt"
ADMIN_LLM = ROOT / "admin" / "llm.json"
PROMPT_FILES = {
    "scene_pack": ADMIN_PACK_PROMPT,
    "media_prompt": ADMIN_MEDIA_PROMPT,
    "script": ADMIN_PROMPT,
    "youtube_doc": ADMIN_DOC_PROMPT,
}

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VID_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

STAGE_DEFS = [
    ("prepare", "대본 분석·미디어 매칭"),
    ("audio", "나레이션 생성 (TTS)"),
    ("timeline", "타임라인 구성"),
    ("subs", "자막 타이밍 (Whisper)"),
    ("base", "베이스 영상 조립 (FFmpeg)"),
    ("overlay", "그래픽 오버레이 (Remotion)"),
    ("mux", "최종 인코딩·먹스"),
]

VOICES = [
    ("ko-KR-SunHiNeural", "선희 — 밝은 여성 (기본)"),
    ("ko-KR-InJoonNeural", "인준 — 차분한 남성"),
    ("ko-KR-JiMinNeural", "지민 — 캐주얼 여성"),
    ("ko-KR-HyunsuNeural", "현수 — 남성"),
    ("ko-KR-YuJinNeural", "유진 — 여성"),
    ("ko-KR-HyunsuMultilingualNeural", "현수 멀티 — 다국어 남성"),
]
# Qwen3-TTS CustomVoice 프리셋 (공식 9종)
QWEN_SPEAKERS = [
    ("Sohee", "소희 — 한국어, 감성적인 여성 (기본)"),
    ("Ryan", "라이언 — 영어 남성, 리듬감"),
    ("Aiden", "에이든 — 영어 남성, 맑은 중음"),
    ("Vivian", "비비안 — 중국어 여성, 밝음"),
    ("Serena", "세레나 — 중국어 여성, 온화"),
    ("Dylan", "딜런 — 베이징 남성"),
    ("Eric", "에릭 — 청두 남성, 허스키"),
    ("Uncle_Fu", "푸 아저씨 — 중년 남성, 저음"),
    ("Ono_Anna", "오노 안나 — 일본어 여성, 발랄"),
]
TTS_ENGINES = [
    ("auto", "auto — qwen→edge→gtts 자동"),
    ("qwen", "Qwen3-TTS (로컬, Sohee)"),
    ("qwen,edge", "Qwen3-TTS + edge-tts 평활"),
    ("edge", "edge-tts (클라우드 신경망)"),
    ("gtts", "gTTS (경량)"),
]
RATES = ["-20%", "-10%", "+0%", "+6%", "+10%", "+20%"]
WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3"]

LOG_LIMIT = 500

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 업로드 최대 4GB

JOBS: dict[str, dict] = {}
JOB_Q: queue.Queue[str] = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()


# ── 유틸 ─────────────────────────────────────────────

def sanitize_name(name: str) -> str:
    """업로드 파일명 정제 (한글/영숫자/._- 유지, 공백→_)."""
    stem, _, ext = name.rpartition(".")
    stem = stem or name
    stem = re.sub(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ._-]+", "_", stem).strip("_") or "media"
    return f"{stem}.{ext}" if ext else stem


def job_public(job: dict) -> dict:
    return {
        "id": job["id"],
        "status": job["status"],          # queued|running|done|error
        "mode": job.get("mode", "final"),  # final|preview
        "stage": job.get("stage"),
        "stage_label": job.get("stage_label"),
        "progress": job.get("progress", 0),
        "log": job["log"][-300:],
        "outputs": job["outputs"],
        "error": job.get("error"),
        "created_at": job["created_at"],
        "script_preview": job["script_text"][:40],
    }


# ── 백그라운드 파이프라인 워커 ─────────────────────────

def run_stage(job: dict, stage: str) -> None:
    cmd = [
        sys.executable, "build.py", stage,
        "--script", str(job["script"]),
        "--media-dir", str(job["media_dir"]),
        "--work-dir", str(job["work_dir"]),
        "--out-dir", str(job["out_dir"]),
        "--voice", job["voice"],
        "--rate", job["rate"],
        "--whisper-model", job["whisper_model"],
        "--watermark", job["watermark"],
        "--padding", str(job["padding"]),
        "--width", str(job.get("width", 1080)),
        "--height", str(job.get("height", 1920)),
        "--fps", str(job.get("fps", 30)),
    ]
    if job.get("subtitle_font"):
        cmd += ["--subtitle-font", str(job["subtitle_font"])]
    if job.get("bgm"):
        cmd += ["--bgm", str(job["bgm"])]
    for flag, cli in [
        ("no_whisper", "--no-whisper"),
        ("no_overlay", "--no-overlay"),
        ("no_duck", "--no-duck"),
        ("loudnorm", "--loudnorm"),
    ]:
        if job.get(flag):
            cmd.append(cli)
    # TTS 엔진(Qwen3-TTS 포함) 체인
    cmd += ["--tts-backend", job.get("tts_backend") or "auto"]
    if "qwen" in (job.get("tts_backend") or ""):
        cmd += ["--qwen-speaker", job.get("qwen_speaker") or "Sohee"]
        if job.get("qwen_model"):
            cmd += ["--qwen-model", job["qwen_model"]]
        if job.get("qwen_instruct"):
            cmd += ["--qwen-instruct", job["qwen_instruct"]]

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        cmd, cwd=ROOT, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        job["log"].append(line.rstrip())
        if len(job["log"]) > LOG_LIMIT:
            del job["log"][: len(job["log"]) - LOG_LIMIT]
    if proc.wait() != 0:
        raise RuntimeError(f"'{stage}' 단계 실패 — 로그를 확인하세요")


def run_job(job: dict) -> None:
    preview_mode = job.get("mode") == "preview"
    if preview_mode:
        stages = [("preview", "합성 미리보기(자막·영상·나레이션)")]
    else:
        stages = [s for s in STAGE_DEFS if not (job.get("no_overlay") and s[0] == "overlay")]
    job["status"] = "running"
    try:
        for i, (key, label) in enumerate(stages, 1):
            job["stage"], job["stage_label"] = key, label
            job["log"].append(f"━━ [{i}/{len(stages)}] {label} ({key}) ━━")
            run_stage(job, key)
            job["progress"] = int(i / len(stages) * 100)
        if preview_mode:
            job["outputs"]["preview"] = (job["out_dir"] / "preview.mp4").exists()
            job["status"] = "done" if job["outputs"]["preview"] else "error"
            if not job["outputs"]["preview"]:
                job["error"] = "preview.mp4가 생성되지 않았습니다."
        else:
            job["outputs"]["video"] = (job["out_dir"] / "final.mp4").exists()
            job["outputs"]["srt"] = (job["out_dir"] / "subtitles.srt").exists()
            job["status"] = "done" if job["outputs"]["video"] else "error"
            if not job["outputs"]["video"]:
                job["error"] = "final.mp4가 생성되지 않았습니다."
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)
        job["log"].append(f"[웹][오류] {e}")


def worker_loop() -> None:
    while True:
        job_id = JOB_Q.get()
        job = JOBS.get(job_id)
        try:
            if job:
                run_job(job)
        except Exception as e:  # noqa: BLE001
            job["status"] = "error"
            job["error"] = str(e)
        finally:
            JOB_Q.task_done()


def ensure_worker() -> None:
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            t = threading.Thread(target=worker_loop, daemon=True, name="shorts-worker")
            t.start()
            _worker_started = True


# ── 라우트 ───────────────────────────────────────────

@app.get("/")
def index():
    return render_template(
        "index.html",
        voices=VOICES,
        rates=RATES,
        whisper_models=WHISPER_MODELS,
        tts_engines=TTS_ENGINES,
        qwen_speakers=QWEN_SPEAKERS,
        defaults=studio_defaults(),
        logged_in=admin_logged_in(),
    )


@app.post("/api/scriptgen")
def api_scriptgen():
    """주제 → 관리자 프롬프트 → AI 대본.

    style:
      * pack (기본): 씬 팩 — 쇼츠 대본 + 씬별 이미지/동영상 프롬프트
      * doc        : 유튜브 공학 다큐 3~5분 — 낭독 대본만(5단계=5씬)
    """
    data = request.get_json(silent=True) or request.form
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "주제를 입력하세요."}), 400
    style = (data.get("style") or "pack").strip()
    try:
        scenes = max(2, min(10, int(data.get("scenes") or 4)))
        duration = max(10, min(120, int(data.get("duration") or 30)))
    except (TypeError, ValueError):
        scenes, duration = 4, 30
    tone = (data.get("tone") or "정보 전달·실용 꿀팁").strip()
    media_lang = (data.get("media_lang") or "English").strip()

    if style == "doc":
        try:
            text = scriptgen.generate_script(
                topic, scenes=5, duration=240, tone=tone,
                prompt_path=ADMIN_DOC_PROMPT, llm_path=ADMIN_LLM,
                llm_overrides=eff_llm_overrides(), template_text=db_prompt("youtube_doc"),
            )
        except scriptgen.ScriptGenError as e:
            return jsonify({"error": str(e)}), 502
        except Exception as e:  # noqa: BLE001
            return jsonify({"error": f"다큐 대본 생성 실패: {e}"}), 500
        n = len([b for b in re.split(r"\n\s*\n", text) if b.strip()])
        return jsonify({"script": text, "scenes": n, "style": "doc",
                        "media_prompts": [], "prompts_text": ""})

    media_lang = (data.get("media_lang") or "English").strip()
    try:
        pack = scriptgen.generate_scene_pack(
            topic, scenes=scenes, duration=duration, tone=tone,
            media_lang=media_lang,
            prompt_path=ADMIN_PACK_PROMPT, llm_path=ADMIN_LLM,
            llm_overrides=eff_llm_overrides(), template_text=db_prompt("scene_pack"),
        )
    except scriptgen.ScriptGenError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"대본 생성 실패: {e}"}), 500

    return jsonify({
        "script": pack.to_script(),
        "scenes": len(pack.scenes),
        "media_prompts": [sc.to_dict() for sc in pack.scenes],
        "prompts_text": pack.to_prompts_text(),
    })


@app.post("/api/mediaprompts")
def api_mediaprompts():
    """완성된 대본(직접 입력/외부 AI) → 씬별 이미지/동영상 프롬프트.

    입력은 빈 줄로 구분된 대본 텍스트. 씬 순서는 그대로 유지된다.
    """
    data = request.get_json(silent=True) or request.form
    script = (data.get("script") or "").strip()
    if not script:
        return jsonify({"error": "대본을 입력하세요."}), 400
    blocks = [b.strip() for b in re.split(r"\n\s*\n", script) if b.strip()]
    # 씬 낯줄바꿈은 파서 규칙대로 공백 정규화
    blocks = [re.sub(r"\s*\n\s*", " ", b) for b in blocks]
    media_lang = (data.get("media_lang") or "English").strip()

    try:
        prompts = scriptgen.generate_media_prompts(
            blocks, media_lang=media_lang,
            prompt_path=ADMIN_MEDIA_PROMPT, llm_path=ADMIN_LLM,
            llm_overrides=eff_llm_overrides(), template_text=db_prompt("media_prompt"),
        )
    except scriptgen.ScriptGenError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"프롬프트 생성 실패: {e}"}), 500

    pack = scriptgen.ScenePack(prompts)
    return jsonify({
        "scenes": len(prompts),
        "media_prompts": [sc.to_dict() for sc in prompts],
        "prompts_text": pack.to_prompts_text(),
    })


@app.post("/api/generate")
def generate():
    script = (request.form.get("script") or "").strip()
    if not script:
        return jsonify({"error": "대본이 비어 있습니다."}), 400

    job_id = uuid.uuid4().hex[:12]
    base = JOBS_ROOT / job_id
    media_dir = base / "media"
    out_dir = base / "out"
    work_dir = base / "work"
    for d in (media_dir, out_dir, work_dir):
        d.mkdir(parents=True, exist_ok=True)

    script_path = base / "script.txt"
    script_path.write_text(script, encoding="utf-8")

    # 작업 모드: final(전체 렌더) | preview(자막·영상·나레이션 합성 미리보기)
    job_mode = request.form.get("job_mode") if request.form.get("job_mode") in ("final", "preview") else "final"

    # 미리보기 해상도 (기본 540×960@24 — 빠른 확인용)
    try:
        pv = {
            "width": max(180, min(1080, int(request.form.get("pv_width") or 540))),
            "height": max(320, min(1920, int(request.form.get("pv_height") or 960))),
            "fps": max(12, min(60, int(request.form.get("pv_fps") or 24))),
        }
    except (TypeError, ValueError):
        pv = {"width": 540, "height": 960, "fps": 24}

    # 미리보기 자막 폰트 업로드(선택)
    subtitle_font_path = None
    font_up = request.files.get("subtitle_font")
    if font_up and font_up.filename and Path(font_up.filename).suffix.lower() in {".ttf", ".otf", ".ttc"}:
        subtitle_font_path = base / ("subtitle_font" + Path(font_up.filename).suffix.lower())
        font_up.save(subtitle_font_path)

    # 미디어 업로드 (번호가 있는 파일명은 그 번호 우선, 아니면 도착 순서)
    saved = 0
    for f in request.files.getlist("media"):
        if not f or not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in IMG_EXTS | VID_EXTS:
            continue
        name = sanitize_name(Path(f.filename).name)
        if not re.match(r"\d+", name):
            name = f"{saved:02d}_{name}"
        f.save(media_dir / name)
        saved += 1

    # 미디어가 하나도 없으면 서버의 assets/media 사용
    use_server = request.form.get("use_server_media") == "1" or saved == 0
    final_media_dir = media_dir
    if use_server:
        server_dir = ROOT / "assets" / "media"
        if any(p.suffix.lower() in IMG_EXTS | VID_EXTS for p in server_dir.glob("*")):
            final_media_dir = server_dir
        elif saved == 0:
            return jsonify({"error": "미디어가 없습니다. 이미지/비디오를 업로드하거나 서버 assets/media에 넣어 주세요."}), 400

    # BGM 업로드(선택)
    bgm_path = None
    bgm = request.files.get("bgm")
    if bgm and bgm.filename and Path(bgm.filename).suffix.lower() in AUDIO_EXTS:
        bgm_path = base / ("bgm" + Path(bgm.filename).suffix.lower())
        bgm.save(bgm_path)
    elif request.form.get("use_server_bgm") == "1":
        candidates = [p for p in (ROOT / "assets" / "bgm").glob("*") if p.suffix.lower() in AUDIO_EXTS]
        if candidates:
            bgm_path = sorted(candidates)[0]

    # 폼에 미디어 프롬프트(JSON)가 실려 오면 작업 
    mp_json = (request.form.get("media_prompts_json") or "").strip()
    if mp_json:
        try:
            mp_list = json.loads(mp_json)
            if isinstance(mp_list, list) and mp_list:
                (out_dir / "media_prompts.json").write_text(mp_json, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            print(f"[웹][경고] media_prompts_json 저장 실패: {e}", file=sys.stderr)

    job = {
        "id": job_id,
        "status": "queued",
        "stage": None,
        "stage_label": None,
        "progress": 0,
        "log": ["[웹] 작업이 접수되었습니다. 대기열에서 기다리는 중…"],
        "outputs": {"video": False, "srt": False, "preview": False},
        "error": None,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "script_text": script,
        "script": script_path,
        "media_dir": final_media_dir,
        "work_dir": work_dir,
        "out_dir": out_dir,
        "voice": request.form.get("voice") or "ko-KR-SunHiNeural",
        "rate": request.form.get("rate") or "+6%",
        "tts_backend": request.form.get("tts_backend") or "auto",
        "qwen_speaker": request.form.get("qwen_speaker") or "Sohee",
        "qwen_model": request.form.get("qwen_model") or "",
        "qwen_instruct": request.form.get("qwen_instruct") or "",
        "whisper_model": request.form.get("whisper_model") or "base",
        "watermark": request.form.get("watermark") or "",
        "padding": request.form.get("padding") or "0.4",
        "bgm": bgm_path,
        "no_whisper": request.form.get("no_whisper") == "1",
        "no_overlay": request.form.get("no_overlay") == "1",
        "no_duck": request.form.get("no_duck") == "1",
        "loudnorm": request.form.get("loudnorm") == "1",
        "mode": job_mode,
        "width": pv["width"] if job_mode == "preview" else 1080,
        "height": pv["height"] if job_mode == "preview" else 1920,
        "fps": pv["fps"] if job_mode == "preview" else 30,
        "subtitle_font": subtitle_font_path,
    }
    JOBS[job_id] = job
    JOB_Q.put(job_id)
    return jsonify({"job_id": job_id, "status_url": f"/api/jobs/{job_id}"})


@app.get("/api/jobs")
def list_jobs():
    jobs = sorted(JOBS_PUBLIC(), key=lambda j: j["created_at"], reverse=True)[:20]
    return jsonify({"jobs": jobs})


def JOBS_PUBLIC():
    return [job_public(j) for j in JOBS.values()]


@app.get("/api/jobs/<job_id>")
def job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404
    return jsonify(job_public(job))


@app.get("/api/download/<job_id>/<kind>")
def download(job_id: str, kind: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "작업을 찾을 수 없습니다."}), 404
    targets = {
        "video": (job["out_dir"] / "final.mp4", f"shorts_{job_id[:8]}.mp4"),
        "preview": (job["out_dir"] / "preview.mp4", f"preview_{job_id[:8]}.mp4"),
        "srt": (job["out_dir"] / "subtitles.srt", f"shorts_{job_id[:8]}.srt"),
    }
    if kind not in targets:
        return jsonify({"error": "잘못된 다운로드 종류"}), 400
    path, dname = targets[kind]
    if not path.exists():
        return jsonify({"error": "아직 결과물이 없습니다."}), 404
    if kind == "preview":  # 인라인 재생(범위 요청 지원) — 미리보기 플레이어용
        return send_file(path, mimetype="video/mp4", as_attachment=False, conditional=True)
    return send_file(path, as_attachment=True, download_name=dname)


# ── 엔트리포인트 ──────────────────────────────────────

ensure_worker()

# ── SQLite 설정 스토어 + 관리자 인증 ─────────────────────
# data/settings.db: 스튜디오 설정/LLM 연결/프롬프트 템플릿/관리자 계정
SETTINGS_DB_PATH = DATA_DIR / "settings.db"

app.secret_key = settings_db.get_or_create_secret(SETTINGS_DB_PATH)


def db_get(key: str, default=None):
    return settings_db.get(SETTINGS_DB_PATH, key, default)


def eff_llm_overrides() -> dict:
    """관리자 DB 'llm.*' → LLM 연결 오버라이드 (파일 llm.json 위에 얹음)."""
    return settings_db.get_section(SETTINGS_DB_PATH, "llm")


def db_prompt(kind: str) -> str | None:
    """DB에 저장된 프롬프트 템플릿 (비어 있으면 파일 사용)."""
    v = db_get(f"prompt.{kind}")
    return v if isinstance(v, str) and v.strip() else None


def studio_defaults() -> dict:
    """메인 폼의 기본값 (관리자가 DB로 바꾸면 여기서 주입)."""
    return settings_db.get_section(SETTINGS_DB_PATH, "studio")


def require_login_enabled() -> bool:
    return bool(db_get("auth.require_login", False))


def admin_logged_in() -> bool:
    return bool(session.get("admin"))


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not admin_logged_in():
            if request.path.startswith("/api/"):
                return jsonify({"error": "관리자 로그인이 필요합니다."}), 401
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    wrapper.__name__ = view.__name__
    return wrapper


_PUBLIC_PATHS = ("/admin/login", "/static", "/favicon")


@app.before_request
def auth_guard():
    """require_login=1이면 관리자 로그인 없이는 아무것도 못 열어봄."""
    if admin_logged_in():
        return None
    if any(request.path.startswith(p) for p in _PUBLIC_PATHS):
        return None
    if require_login_enabled():
        if request.path.startswith("/api/"):
            return jsonify({"error": "로그인이 필요합니다. 관리자 로그인 후 이용하세요."}), 401
        return redirect(url_for("admin_login", next=request.path))
    return None


# ── 관리자 라우트 ─────────────────────────────────────

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    need_setup = settings_db.admin_count(SETTINGS_DB_PATH) == 0
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""
        try:
            if need_setup or request.form.get("mode") == "setup":
                if password != password2:
                    raise ValueError("비밀번호 확인이 일치하지 않습니다.")
                settings_db.create_admin(SETTINGS_DB_PATH, username, password)
                session["admin"] = username
                return redirect(safe_next(request.form.get("next")) or url_for("admin_page"))
            if settings_db.verify_admin(SETTINGS_DB_PATH, username, password):
                session["admin"] = username
                return redirect(safe_next(request.form.get("next")) or url_for("admin_page"))
            error = "사용자 이름 또는 비밀번호가 올바르지 않습니다."
        except ValueError as e:
            error = str(e)
    return render_template(
        "login.html", need_setup=need_setup, error=error,
        next=request.values.get("next", ""),
    )


def safe_next(target: str | None) -> str | None:
    """오픈 리디렉션 방지: 같은 사이트 상대 경로만 허용."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


@app.get("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect(url_for("index") if not require_login_enabled() else url_for("admin_login"))


@app.get("/admin")
@admin_required
def admin_page():
    llm_cfg = {
        "provider": db_get("llm.provider", ""),
        "model": db_get("llm.model", ""),
        "base_url": db_get("llm.base_url", ""),
        "api_key_env": db_get("llm.api_key_env", ""),
        "temperature": db_get("llm.temperature", ""),
        "max_tokens": db_get("llm.max_tokens", ""),
    }
    prompts = {
        k: (db_prompt(k) or (f.read_text(encoding="utf-8") if f.exists() else ""))
        for k, f in PROMPT_FILES.items()
    }
    prompts_from_db = {k: bool(db_prompt(k)) for k in PROMPT_FILES}
    return render_template(
        "admin.html",
        admin=session.get("admin"),
        db_path=str(SETTINGS_DB_PATH.relative_to(ROOT)),
        llm_cfg=llm_cfg,
        llm_touched=bool(eff_llm_overrides()),
        prompts=prompts,
        prompts_from_db=prompts_from_db,
        studio=studio_defaults(),
        require_login=require_login_enabled(),
        tts_engines=TTS_ENGINES,
        voices=VOICES,
        rates=RATES,
        qwen_speakers=QWEN_SPEAKERS,
        whisper_models=WHISPER_MODELS,
    )


@app.post("/admin/settings")
@admin_required
def admin_settings_save():
    """관리자 대시보드 폼 저장. 빈 값 = 키 삭제(파일/코드 기본값으로 회귀)."""
    form = request.form
    for key in ("provider", "model", "base_url", "api_key_env", "temperature", "max_tokens"):
        v = (form.get(f"llm_{key}") or "").strip()
        if v:
            if key == "temperature":
                v = float(v)
            elif key == "max_tokens":
                v = int(v)
            settings_db.set(SETTINGS_DB_PATH, f"llm.{key}", v)
        else:
            settings_db.delete(SETTINGS_DB_PATH, f"llm.{key}")

    for kind in PROMPT_FILES:
        v = (form.get(f"prompt_{kind}") or "").strip()
        if v:
            settings_db.set(SETTINGS_DB_PATH, f"prompt.{kind}", v)
        else:
            settings_db.delete(SETTINGS_DB_PATH, f"prompt.{kind}")

    STUDIO_KEYS = ("voice", "rate", "tts_backend", "qwen_speaker", "qwen_instruct",
                   "watermark", "padding", "whisper_model", "width", "height", "fps")
    for key in STUDIO_KEYS:
        v = (form.get(f"studio_{key}") or "").strip()
        if v:
            if key == "padding":
                v = float(v)
            elif key in ("width", "height", "fps"):
                v = int(v)
            settings_db.set(SETTINGS_DB_PATH, f"studio.{key}", v)
        else:
            settings_db.delete(SETTINGS_DB_PATH, f"studio.{key}")

    settings_db.set(SETTINGS_DB_PATH, "auth.require_login", form.get("require_login") == "1")
    return redirect(url_for("admin_page", saved="1"))


@app.post("/admin/password")
@admin_required
def admin_password_change():
    current = request.form.get("current") or ""
    new = request.form.get("new") or ""
    user = session.get("admin")
    if not settings_db.verify_admin(SETTINGS_DB_PATH, user, current):
        return redirect(url_for("admin_page", err="현재 비밀번호가 올바르지 않습니다."))
    try:
        settings_db.change_password(SETTINGS_DB_PATH, user, new)
    except ValueError as e:
        return redirect(url_for("admin_page", err=str(e)))
    return redirect(url_for("admin_page", saved="1"))

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="반자동 쇼츠 조립 시스템 웹 UI")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    JOBS_ROOT.mkdir(exist_ok=True)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)

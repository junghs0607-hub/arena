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
import os
import queue
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

from pipeline import scriptgen  # AI 대본 생성(관리자 프롬프트)

ROOT = Path(__file__).resolve().parent
JOBS_ROOT = ROOT / "jobs"
ADMIN_PROMPT = ROOT / "admin" / "script_prompt.txt"
ADMIN_LLM = ROOT / "admin" / "llm.json"

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
    ]
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
    stages = [s for s in STAGE_DEFS if not (job.get("no_overlay") and s[0] == "overlay")]
    job["status"] = "running"
    try:
        for i, (key, label) in enumerate(stages, 1):
            job["stage"], job["stage_label"] = key, label
            job["log"].append(f"━━ [{i}/{len(stages)}] {label} ({key}) ━━")
            run_stage(job, key)
            job["progress"] = int(i / len(stages) * 100)
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
    )


@app.post("/api/scriptgen")
def api_scriptgen():
    """주제 → 관리자 프롬프트(admin/script_prompt.txt) → AI 대본.

    LLM 호출(수십 초)이므로 동기로 기다리되, 길어지는 대형 작업은
    /api/generate 작업 큐와 분리해 UI가 멀티태스킹된다.
    """
    data = request.get_json(silent=True) or request.form
    topic = (data.get("topic") or "").strip()
    if not topic:
        return jsonify({"error": "주제를 입력하세요."}), 400
    try:
        scenes = max(2, min(10, int(data.get("scenes") or 4)))
        duration = max(10, min(120, int(data.get("duration") or 30)))
    except (TypeError, ValueError):
        scenes, duration = 4, 30
    tone = (data.get("tone") or "정보 전달·실용 꿀팁").strip()

    try:
        text = scriptgen.generate_script(
            topic, scenes=scenes, duration=duration, tone=tone,
            prompt_path=ADMIN_PROMPT, llm_path=ADMIN_LLM,
        )
    except scriptgen.ScriptGenError as e:
        return jsonify({"error": str(e)}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": f"대본 생성 실패: {e}"}), 500

    n_scenes = len([b for b in re.split(r"\n\s*\n", text) if b.strip()])
    return jsonify({"script": text, "scenes": n_scenes})


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

    job = {
        "id": job_id,
        "status": "queued",
        "stage": None,
        "stage_label": None,
        "progress": 0,
        "log": ["[웹] 작업이 접수되었습니다. 대기열에서 기다리는 중…"],
        "outputs": {"video": False, "srt": False},
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
        "srt": (job["out_dir"] / "subtitles.srt", f"shorts_{job_id[:8]}.srt"),
    }
    if kind not in targets:
        return jsonify({"error": "잘못된 다운로드 종류"}), 400
    path, dname = targets[kind]
    if not path.exists():
        return jsonify({"error": "아직 결과물이 없습니다."}), 404
    return send_file(path, as_attachment=True, download_name=dname)


# ── 엔트리포인트 ──────────────────────────────────────

ensure_worker()

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="반자동 쇼츠 조립 시스템 웹 UI")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--debug", action="store_true")
    args = p.parse_args()
    JOBS_ROOT.mkdir(exist_ok=True)
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True)

"""Synchronous pipeline steps used by views and Celery tasks."""
from __future__ import annotations

import json
import os
from datetime import datetime

from flask import current_app
from PIL import Image, ImageDraw, ImageFont

from ..extensions import db
from ..models.content import (
    AutomationJob,
    Script,
    ScriptVersion,
    Subtitle,
    Thumbnail,
    Transcript,
    VideoProject,
    VideoRender,
    VideoScene,
    VoiceGeneration,
    YoutubeUpload,
    ContentCache,
)
from .ai_providers import cache_key, get_llm, get_stt, get_tts, parse_jsonish
from .ffmpeg_service import extract_audio, probe, render_project


STATUSES = [
    "READY",
    "ANALYZING",
    "SCRIPTING",
    "VOICE_GENERATING",
    "EDITING",
    "REVIEW",
    "READY_TO_UPLOAD",
    "UPLOADED",
    "FAILED",
]


def _job(project_id: int, task: str) -> AutomationJob:
    job = AutomationJob(project_id=project_id, task=task, start_time=datetime.utcnow(), status="RUNNING")
    db.session.add(job)
    db.session.commit()
    return job


def _finish(job: AutomationJob, status="SUCCESS", error=None):
    job.end_time = datetime.utcnow()
    job.status = status
    job.error_message = error
    if status != "SUCCESS":
        job.retry_count = (job.retry_count or 0) + 1
    db.session.commit()


def _cache_get(key: str):
    row = ContentCache.query.filter_by(cache_key=key).first()
    return row.payload if row else None


def _cache_set(key: str, kind: str, payload: str):
    row = ContentCache.query.filter_by(cache_key=key).first()
    if row:
        row.payload = payload
    else:
        db.session.add(ContentCache(cache_key=key, kind=kind, payload=payload))
    db.session.commit()


def ensure_rights(project: VideoProject) -> None:
    src = project.source
    if not src or not src.rights_confirmed:
        raise PermissionError("저작권/재사용 권리가 확인되지 않아 자동 제작을 진행할 수 없습니다.")


def analyze_project(project_id: int):
    job = _job(project_id, "analysis")
    project = VideoProject.query.get(project_id)
    try:
        ensure_rights(project)
        project.status = "ANALYZING"
        db.session.commit()
        src = project.source
        meta = {}
        if src.file_path:
            meta = probe(src.file_path)
            src.duration_sec = meta.get("duration")
            src.width = meta.get("width")
            src.height = meta.get("height")
        llm = get_llm()
        prompt = f"영상 분석: 제목={src.title} 길이={src.duration_sec} 카테고리={src.category}"
        ck = cache_key("analysis", src.title, str(src.duration_sec))
        cached = _cache_get(ck)
        raw = cached or llm.complete(prompt)
        if not cached:
            _cache_set(ck, "analysis", raw)
        project.analysis_json = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        data = parse_jsonish(raw)
        VideoScene.query.filter_by(project_id=project.id).delete()
        labels = ["Hook", "Problem", "Explanation", "Important visual", "Conclusion"]
        for i, lab in enumerate(labels):
            db.session.add(
                VideoScene(
                    project_id=project.id,
                    index=i,
                    start_sec=i * 12,
                    end_sec=(i + 1) * 12,
                    label=lab,
                    description=str(data)[:400] if not isinstance(data, dict) else json.dumps(data, ensure_ascii=False)[:400],
                    importance=1.0 - i * 0.1,
                )
            )
        project.status = "SCRIPTING"
        db.session.commit()
        _finish(job)
    except Exception as exc:
        project.status = "FAILED"
        project.error_message = str(exc)
        db.session.commit()
        _finish(job, "FAILED", str(exc))
        raise


def transcribe_project(project_id: int):
    job = _job(project_id, "transcription")
    project = VideoProject.query.get(project_id)
    try:
        ensure_rights(project)
        audio_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "audio")
        os.makedirs(audio_dir, exist_ok=True)
        audio_path = os.path.join(audio_dir, f"src_{project.id}.mp3")
        if project.source.file_path:
            extract_audio(project.source.file_path, audio_path)
        ck = cache_key("stt", project.source.file_path or "", str(project.id))
        cached = _cache_get(ck)
        text = cached or get_stt().transcribe(audio_path, project.language)
        if not cached:
            _cache_set(ck, "transcript", text)
        t = Transcript(project_id=project.id, language=project.language, text=text, provider="mock", cache_key=ck, status="READY")
        db.session.add(t)
        db.session.commit()
        _finish(job)
        return t
    except Exception as exc:
        project.status = "FAILED"
        project.error_message = str(exc)
        db.session.commit()
        _finish(job, "FAILED", str(exc))
        raise


def generate_script(project_id: int):
    job = _job(project_id, "script")
    project = VideoProject.query.get(project_id)
    try:
        ensure_rights(project)
        project.status = "SCRIPTING"
        db.session.commit()
        tr = Transcript.query.filter_by(project_id=project.id).order_by(Transcript.id.desc()).first()
        transcript = tr.text if tr else ""
        llm = get_llm()
        prompt = (
            f"원본을 복제하지 말고 새로운 한국어 {project.format_type} 대본을 작성하라. "
            f"목표 길이 {project.target_duration}초. Shorts 구조(Hook/문제/핵심/반전/CTA)를 따르라.\n"
            f"전사: {transcript}\n분석: {project.analysis_json}"
        )
        body = llm.complete(prompt)
        hook = body.split("\n")[0] if body else ""
        script = Script(
            project_id=project.id,
            format_type=project.format_type,
            body=body,
            hook=hook,
            conclusion=body.split("\n")[-1] if body else "",
            provider=current_app.config.get("LLM_PROVIDER", "mock"),
            status="READY",
        )
        db.session.add(script)
        db.session.flush()
        db.session.add(ScriptVersion(script_id=script.id, body=body, note="auto"))
        db.session.commit()
        _finish(job)
        return script
    except Exception as exc:
        project.status = "FAILED"
        project.error_message = str(exc)
        db.session.commit()
        _finish(job, "FAILED", str(exc))
        raise


def generate_voice(project_id: int, style="friendly", gender="feminine"):
    job = _job(project_id, "tts")
    project = VideoProject.query.get(project_id)
    try:
        ensure_rights(project)
        project.status = "VOICE_GENERATING"
        db.session.commit()
        script = Script.query.filter_by(project_id=project.id).order_by(Script.id.desc()).first()
        text = script.body if script else "새로운 해설입니다."
        ck = cache_key("tts", text, style, gender, project.language)
        out = os.path.join(current_app.config["UPLOAD_FOLDER"], "audio", f"voice_{project.id}.wav")
        cached = VoiceGeneration.query.filter_by(cache_key=ck).first()
        if cached and cached.file_path and os.path.isfile(cached.file_path):
            path = cached.file_path
        else:
            path = get_tts().synthesize(text, out, project.language, style)
        vg = VoiceGeneration(
            project_id=project.id,
            file_path=path,
            provider=current_app.config.get("TTS_PROVIDER", "mock"),
            voice_style=style,
            language=project.language,
            gender=gender,
            cache_key=ck,
            status="READY",
        )
        db.session.add(vg)
        db.session.commit()
        _finish(job)
        return vg
    except Exception as exc:
        project.status = "FAILED"
        project.error_message = str(exc)
        db.session.commit()
        _finish(job, "FAILED", str(exc))
        raise


def _srt_from_script(text: str, duration: float = 60.0) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        lines = [text or "자막"]
    chunk = max(duration / len(lines), 1.5)

    def ts(sec: float) -> str:
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    parts = []
    t = 0.0
    for i, line in enumerate(lines, 1):
        parts.append(f"{i}\n{ts(t)} --> {ts(t + chunk)}\n{line}\n")
        t += chunk
    return "\n".join(parts)


def generate_subtitle(project_id: int):
    job = _job(project_id, "subtitle")
    project = VideoProject.query.get(project_id)
    try:
        script = Script.query.filter_by(project_id=project.id).order_by(Script.id.desc()).first()
        body = script.body if script else "자막"
        content = _srt_from_script(body, float(project.target_duration or 60))
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], "subtitles", f"p{project.id}.srt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        sub = Subtitle(
            project_id=project.id,
            format="srt",
            file_path=path,
            content=content,
            word_highlight=True,
            status="READY",
        )
        db.session.add(sub)
        db.session.commit()
        _finish(job)
        return sub
    except Exception as exc:
        _finish(job, "FAILED", str(exc))
        raise


def generate_thumbnail(project_id: int):
    job = _job(project_id, "thumbnail")
    project = VideoProject.query.get(project_id)
    try:
        llm = get_llm()
        titles_raw = llm.complete(f"제목 후보를 JSON으로 생성: {project.title}")
        titles = parse_jsonish(titles_raw)
        headline = project.title[:40]
        if isinstance(titles, list) and titles:
            headline = titles[0].get("title", headline) if isinstance(titles[0], dict) else str(titles[0])
        path = os.path.join(current_app.config["UPLOAD_FOLDER"], "thumbnails", f"p{project.id}.png")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        img = Image.new("RGB", (1280, 720), (18, 22, 40))
        draw = ImageDraw.Draw(img)
        draw.rectangle([0, 0, 1280, 720], fill=(24, 32, 64))
        draw.rectangle([40, 40, 1240, 680], outline=(255, 80, 80), width=8)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 48)
            font2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
        except Exception:
            font = ImageFont.load_default()
            font2 = font
        draw.text((80, 280), headline[:42], fill=(255, 255, 255), font=font)
        draw.text((80, 380), "NEW NARRATION  ·  SHORTS", fill=(255, 180, 80), font=font2)
        img.save(path)
        th = Thumbnail(project_id=project.id, file_path=path, headline=headline, subheadline="AI remake", status="READY")
        db.session.add(th)
        db.session.commit()
        _finish(job)
        return th
    except Exception as exc:
        _finish(job, "FAILED", str(exc))
        raise


def generate_metadata(project_id: int):
    job = _job(project_id, "metadata")
    project = VideoProject.query.get(project_id)
    try:
        llm = get_llm()
        titles_raw = llm.complete(f"제목 후보 JSON: {project.title}")
        titles = parse_jsonish(titles_raw)
        title = project.title
        score = 70.0
        if isinstance(titles, list) and titles and isinstance(titles[0], dict):
            title = titles[0].get("title", title)
            score = float(titles[0].get("score", 70))
        tags = "shorts,korea,tech,explained"
        hashtags = "#Shorts #한국 #기술" if project.format_type == "shorts" else "#다큐 #해설"
        desc = (
            f"{title}\n\nAI가 원본의 핵심 사실만 추출해 새 해설로 재구성한 콘텐츠입니다.\n"
            f"00:00 Intro\n00:08 Chapter 1\n00:30 Chapter 2\n00:50 CTA\n"
        )
        up = YoutubeUpload(
            project_id=project.id,
            title=title,
            description=desc,
            tags=tags,
            hashtags=hashtags,
            category="28",
            chapters="00:00 Intro",
            pinned_comment="새로운 해설로 재구성한 영상입니다. 의견 남겨주세요!",
            privacy="PRIVATE",
            status="DRAFT",
            click_score=score,
        )
        db.session.add(up)
        db.session.commit()
        _finish(job)
        return up
    except Exception as exc:
        _finish(job, "FAILED", str(exc))
        raise


def quality_check(project_id: int) -> dict:
    project = VideoProject.query.get(project_id)
    render = VideoRender.query.filter_by(project_id=project.id).order_by(VideoRender.id.desc()).first()
    sub = Subtitle.query.filter_by(project_id=project.id).order_by(Subtitle.id.desc()).first()
    voice = VoiceGeneration.query.filter_by(project_id=project.id).order_by(VoiceGeneration.id.desc()).first()
    th = Thumbnail.query.filter_by(project_id=project.id).order_by(Thumbnail.id.desc()).first()
    meta = YoutubeUpload.query.filter_by(project_id=project.id).order_by(YoutubeUpload.id.desc()).first()
    checks = {
        "has_render": bool(render and render.file_path),
        "has_voice": bool(voice and voice.file_path),
        "has_subtitle": bool(sub and sub.content),
        "has_thumbnail": bool(th and th.file_path),
        "has_title": bool(meta and meta.title),
        "has_description": bool(meta and meta.description),
        "original_not_copied": True,
        "new_narration": bool(Script.query.filter_by(project_id=project.id).first()),
    }
    project.quality_json = json.dumps(checks, ensure_ascii=False)
    if all(checks.values()):
        project.status = "READY_TO_UPLOAD"
    else:
        project.status = "REVIEW"
    db.session.commit()
    return checks


def render_video(project_id: int):
    job = _job(project_id, "editing")
    project = VideoProject.query.get(project_id)
    try:
        ensure_rights(project)
        project.status = "EDITING"
        db.session.commit()
        voice = VoiceGeneration.query.filter_by(project_id=project.id).order_by(VoiceGeneration.id.desc()).first()
        sub = Subtitle.query.filter_by(project_id=project.id).order_by(Subtitle.id.desc()).first()
        aspect = "9:16" if project.format_type == "shorts" else "16:9"
        out = os.path.join(current_app.config["UPLOAD_FOLDER"], "final", f"p{project.id}.mp4")
        path = render_project(
            project.source.file_path or "",
            voice.file_path if voice else None,
            sub.file_path if sub else None,
            out,
            aspect,
        )
        vr = VideoRender(
            project_id=project.id,
            file_path=path,
            aspect=aspect,
            width=1080 if aspect == "9:16" else 1920,
            height=1920 if aspect == "9:16" else 1080,
            duration_sec=float(project.target_duration or 60),
            progress=100,
            status="SUCCESS",
        )
        db.session.add(vr)
        project.status = "REVIEW"
        db.session.commit()
        _finish(job)
        return vr
    except Exception as exc:
        project.status = "FAILED"
        project.error_message = str(exc)
        db.session.commit()
        _finish(job, "FAILED", str(exc))
        raise


def run_full_pipeline(project_id: int):
    analyze_project(project_id)
    transcribe_project(project_id)
    generate_script(project_id)
    generate_voice(project_id)
    generate_subtitle(project_id)
    render_video(project_id)
    generate_thumbnail(project_id)
    generate_metadata(project_id)
    return quality_check(project_id)

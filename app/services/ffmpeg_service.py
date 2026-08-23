"""FFmpeg wrappers. Commands are built from validated numeric/path args only."""
import json
import os
import shutil
import subprocess
from typing import Optional


class FFmpegError(RuntimeError):
    pass


def _run(args: list[str]) -> str:
    if not args or args[0] not in ("ffmpeg", "ffprobe"):
        raise FFmpegError("허용되지 않은 명령입니다.")
    try:
        proc = subprocess.run(
            args,
            check=True,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return proc.stdout
    except FileNotFoundError as exc:
        raise FFmpegError("FFmpeg가 설치되어 있지 않습니다.") from exc
    except subprocess.CalledProcessError as exc:
        raise FFmpegError(exc.stderr or str(exc)) from exc


def probe(path: str) -> dict:
    if not os.path.isfile(path):
        return {"duration": 0, "width": 0, "height": 0}
    if not shutil.which("ffprobe"):
        return {"duration": 12.0, "width": 1280, "height": 720, "mock": True}
    out = _run(
        [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
    )
    data = json.loads(out or "{}")
    duration = float(data.get("format", {}).get("duration") or 0)
    width = height = 0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video":
            width = int(s.get("width") or 0)
            height = int(s.get("height") or 0)
            break
    return {"duration": duration, "width": width, "height": height}


def extract_audio(video_path: str, audio_path: str) -> str:
    os.makedirs(os.path.dirname(audio_path), exist_ok=True)
    if not shutil.which("ffmpeg"):
        with open(audio_path, "wb") as f:
            f.write(b"MOCKAUDIO")
        return audio_path
    _run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "mp3", audio_path])
    return audio_path


def render_project(
    source_path: str,
    audio_path: Optional[str],
    subtitle_path: Optional[str],
    output_path: str,
    aspect: str = "9:16",
) -> str:
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if not shutil.which("ffmpeg") or not source_path or not os.path.isfile(source_path):
        # Generate a tiny placeholder mp4-like file for demo
        with open(output_path, "wb") as f:
            f.write(b"\x00\x00\x00\x18ftypmp42MOCKRENDER")
        return output_path

    if aspect == "9:16":
        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
        size = ["-s", "1080x1920"]
    elif aspect == "1:1":
        vf = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
        size = ["-s", "1080x1080"]
    else:
        vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"
        size = ["-s", "1920x1080"]

    if subtitle_path and os.path.isfile(subtitle_path):
        # escape path for subtitles filter
        escaped = subtitle_path.replace("\\", "/").replace(":", "\\:")
        vf = f"{vf},subtitles='{escaped}'"

    args = ["ffmpeg", "-y", "-i", source_path]
    if audio_path and os.path.isfile(audio_path):
        args += ["-i", audio_path, "-map", "0:v:0", "-map", "1:a:0", "-shortest"]
    args += ["-vf", vf, *size, "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path]
    _run(args)
    return output_path

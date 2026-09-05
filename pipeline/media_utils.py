"""미디어 수집/분석 (ffprobe 우선, 없으면 ffmpeg -i 파싱 평활 경로).

미디어 파일은 이름 앞에 번호를 붙여 두면
씬 순서와 1:1 매칭된다. (01_hook.mp4, 02_point1.jpg, ...)
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .common import fail, find_binary, log, natural_key, run, warn

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VID_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


@dataclass
class MediaInfo:
    path: Path
    kind: str  # "image" | "video"
    duration: float  # 이미지는 0.0
    width: int = 0
    height: int = 0

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "kind": self.kind,
            "duration": round(self.duration, 3),
            "width": self.width,
            "height": self.height,
        }


def collect_media(media_dir: Path) -> list[MediaInfo]:
    media_dir = Path(media_dir)
    files = sorted(
        [p for p in media_dir.iterdir() if p.suffix.lower() in IMG_EXTS | VID_EXTS],
        key=natural_key,
    )
    if not files:
        fail(
            f"미디어 폴더({media_dir})가 비어 있습니다(장면 이미지/비디오 없음).\n"
            "이미지/비디오를 생성·다운로드해 넣어 주세요. "
            "(이름 앞 번호 = 씬 순서)"
        )
    infos: list[MediaInfo] = []
    for f in files:
        ext = f.suffix.lower()
        if ext in IMG_EXTS:
            infos.append(MediaInfo(path=f, kind="image", duration=0.0))
        else:
            d, w, h = probe(f)
            infos.append(MediaInfo(path=f, kind="video", duration=d, width=w, height=h))
            log(f"  미디어: {f.name}  ({d:.2f}s, {w}x{h})")
    return infos


def match_scenes_to_media(scenes: list, media: list[MediaInfo]) -> list[MediaInfo]:
    """씬 i ↔ 미디어 i. 개수가 다륵면 마지막 미디어를 재사용(경고)."""
    if len(media) < len(scenes):
        warn(f"미디어({len(media)}개)가 씬({len(scenes)}개)보다 적습니다. 마지막 미디어를 반복 사용합니다.")
        media = media + [media[-1]] * (len(scenes) - len(media))
    elif len(media) > len(scenes):
        warn(f"미디어({len(media)}개)가 씬({len(scenes)}개)보다 많습니다. 앞에서 {len(scenes)}개만 사용합니다.")
    return media[: len(scenes)]


# ── 길이/해상도 프로브 ──────────────────────────────────

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO_RE = re.compile(r"Stream .*Video:.*? (\d{2,6})x(\d{2,6})")


def probe(path: Path) -> tuple[float, int, int]:
    """(duration_sec, width, height). ffprobe 우선, 없으면 ffmpeg -i 평활."""
    ffprobe = find_binary("ffprobe")
    if ffprobe:
        proc = run(
            [
                ffprobe, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            desc=f"ffprobe {path.name}",
        )
        data = json.loads(proc.stdout or "{}")
        dur = float(data.get("format", {}).get("duration", 0.0))
        w = h = 0
        for s in data.get("streams", []):
            if s.get("codec_type") == "video":
                w, h = int(s.get("width", 0)), int(s.get("height", 0))
                break
        return dur, w, h

    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        fail("ffmpeg/ffprobe를 찾을 수 없습니다. ffmpeg를 설치하거나 `pip install imageio-ffmpeg`를 사용하세요.")
    import subprocess

    proc = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    text = proc.stderr or ""
    m = _DURATION_RE.search(text)
    dur = 0.0
    if m:
        hh, mm, ss = m.groups()
        dur = int(hh) * 3600 + int(mm) * 60 + float(ss)
    vm = _VIDEO_RE.search(text)
    w, h = (int(vm.group(1)), int(vm.group(2))) if vm else (0, 0)
    return dur, w, h


def probe_duration(path: Path) -> float:
    d, _, _ = probe(path)
    return d

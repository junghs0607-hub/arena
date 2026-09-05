"""타임라인 빌더: 씬/미디어/오디오 → 절대 시간 타임라인 JSON.

이 JSON이 파이프라인의 '단일 진실 소스(single source of truth)'다.
  * FFmpeg 베이스 조립은 scenes[].duration 을 그대로 따르고
  * Whisper 자막 정렬은 scenes[].start 를 오프셋으로 사용하며
  * Remotion 오버레이는 fps/total_duration/subtitles 를 읽어 렌더링한다.
길이는 모두 프레임 격자로 양자화해 A/V 싱크 드리프트를 없앤다.
"""
from __future__ import annotations

import json
from pathlib import Path

from .common import log
from .config import Settings


def quantize_to_frames(seconds: float, fps: int, min_frames: int = 1) -> float:
    frames = max(min_frames, round(seconds * fps))
    return frames / fps


def build_timeline(
    scenes: list,            # pipeline.script_parser.Scene
    media_map: list,         # pipeline.media_utils.MediaInfo
    audio_paths: list[Path],
    audio_durs: list[float],
    s: Settings,
) -> dict:
    fps = s.fps
    timeline_scenes = []
    cursor = 0.0
    for sc, mi, apath, adur in zip(scenes, media_map, audio_paths, audio_durs):
        raw = adur + s.scene_padding
        dur = quantize_to_frames(raw, fps, min_frames=int(fps * 0.5))
        timeline_scenes.append(
            {
                "index": sc.index,
                "text": sc.text,
                "sentences": sc.sentences,
                "media": str(Path(mi.path).resolve()),
                "media_type": mi.kind,
                "media_duration": round(mi.duration, 3),
                "audio": str(Path(apath).resolve()),
                "audio_duration": round(adur, 3),
                "start": round(cursor, 4),
                "duration": round(dur, 4),
            }
        )
        log(f"  씬 {sc.index}: start={cursor:6.2f}s  dur={dur:5.2f}s  media={Path(mi.path).name}")
        cursor += dur

    timeline = {
        "version": 1,
        "fps": fps,
        "width": s.width,
        "height": s.height,
        "total_duration": round(cursor, 4),
        "watermark": s.watermark,
        "scenes": timeline_scenes,
        "subtitles": [],  # timestamps 단계에서 채움
    }
    save_timeline(timeline, s)
    log(f"타임라인: {len(timeline_scenes)}씬, 총 {cursor:.2f}s -> {s.timeline_path}")
    return timeline


def save_timeline(timeline: dict, s: Settings) -> None:
    s.timeline_path.write_text(
        json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_timeline(s: Settings) -> dict:
    return json.loads(s.timeline_path.read_text(encoding="utf-8"))

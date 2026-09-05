"""FFmpeg 베이스 조립: 씬 미디어를 1080x1920@30fps 세그먼트로 정규화해 concat.

  * 비디오 클립: 짧으면 -stream_loop 로 반복, cover 크롭으로 세로화
  * 이미지:     zoompan Ken Burns(서서히 확대) 효과 → 지루한 정지화면 방지
  * 모든 세그먼트는 동일 파라미터(x264/yuv420p/무음)로 만들어
    concat demuxer + -c copy 로 무재인코딩 고속 병합
"""
from __future__ import annotations

from pathlib import Path

from .common import fail, find_binary, log, run
from .config import Settings


def _cover_vf(s: Settings) -> str:
    """세로 쇼츠 규격 cover 크롭 필터."""
    return (
        f"scale={s.width}:{s.height}:force_original_aspect_ratio=increase:force_divisible_by=2,"
        f"crop={s.width}:{s.height},fps={s.fps},setsar=1,format=yuv420p"
    )


def _kenburns_vf(s: Settings, frames: int) -> str:
    """이미지 줌인 필터. 입력을 3배 해상도로 올려 zoompan 떨림을 억제."""
    W3, H3 = s.width * 3, s.height * 3
    step = 0.12 / max(1, frames)  # 전체 재생 동안 약 12% 줌인
    return (
        f"scale={W3}:{H3}:force_original_aspect_ratio=increase:force_divisible_by=2,"
        f"crop={W3}:{H3},"
        f"zoompan=z='min(zoom+{step:.8f},1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
        f"s={s.width}x{s.height}:fps={s.fps},"
        "setsar=1,format=yuv420p"
    )


def render_segment(scene: dict, s: Settings, out: Path, force: bool = False) -> Path:
    if out.exists() and not force:
        log(f"  세그먼트 캐시 재사용: {out.name}")
        return out

    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        fail("ffmpeg를 찾을 수 없습니다.")

    dur = scene["duration"]
    frames = max(1, round(dur * s.fps))
    media = scene["media"]

    if scene["media_type"] == "image":
        input_args = ["-loop", "1", "-framerate", str(s.fps), "-t", f"{dur:.4f}", "-i", media]
        vf = _kenburns_vf(s, frames)
    else:
        # 영상이 나레이션보다 짧으면 반복, 길면 잘라냄
        input_args = ["-stream_loop", "-1", "-i", media, "-t", f"{dur:.4f}"]
        vf = _cover_vf(s)

    run(
        [
            ffmpeg, "-y", *input_args,
            "-vf", vf, "-r", str(s.fps),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out),
        ],
        desc=f"씬 {scene['index']} 세그먼트 ({scene['media_type']}, {dur:.2f}s)",
    )
    return out


def build_base(timeline: dict, s: Settings, force: bool = False) -> Path:
    s.segments_dir.mkdir(parents=True, exist_ok=True)
    segs: list[Path] = []
    for scene in timeline["scenes"]:
        segs.append(render_segment(scene, s, s.segments_dir / f"seg_{scene['index']:02d}.mp4", force))

    list_file = s.work_dir / "concat.txt"
    list_file.write_text("".join(f"file '{p.resolve()}'\n" for p in segs), encoding="utf-8")
    ffmpeg = find_binary("ffmpeg")
    run(
        [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(s.base_video_path)],
        desc="베이스 영상 concat",
    )
    log(f"  base.mp4 완성 ({timeline['total_duration']:.2f}s)")
    return s.base_video_path

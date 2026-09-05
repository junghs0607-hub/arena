"""최종 조립(mux): 베이스 영상 (+Remotion 오버레이) + 나레이션 + BGM.

오디오 설계:
  * BGM이 있으면 -stream_loop 로 총 길이까지 반복
  * duck_bgm: sidechaincompress 로 나레이션 구간에서 BGM을 자동 감쇠
    (방송국 덕킹과 동일 원리, 키 입력=나레이션)
  * loudnorm 옵션: EBU R128 (-14 LUFS) 정규화 (플랫폼 권장 음량)
영상:
  * 오버레이 있음: [base][overlay] overlay=0:0 → yuv420p, x264 재인코딩 1회
  * 오버레이 생략(--no-overlay): 베이스를 그대로 톤만 맞춰 인코딩 (급속 미리보기)
"""
from __future__ import annotations

from pathlib import Path

from .common import fail, find_binary, log, run
from .config import Settings


def mux_final(timeline: dict, s: Settings) -> Path:
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        fail("ffmpeg를 찾을 수 없습니다.")

    dur = timeline["total_duration"]
    s.out_dir.mkdir(parents=True, exist_ok=True)

    use_overlay = s.use_overlay and s.overlay_path.exists()
    if s.use_overlay and not use_overlay:
        fail(
            f"오버레이({s.overlay_path})가 없습니다.\n"
            "`python build.py overlay`를 먼저 실행하거나, --no-overlay 로 생략하세요."
        )

    # 입력 인덱스 동적 구성 (오버레이/BGM 유무에 따라 달라짐)
    inputs: list[str] = ["-i", str(s.base_video_path)]
    next_i = 1
    ov_i = None
    if use_overlay:
        inputs += ["-i", str(s.overlay_path)]
        ov_i = next_i
        next_i += 1
    narr_i = next_i
    inputs += ["-i", str(s.narration_path)]
    next_i += 1
    bgm_i = None
    use_bgm = s.bgm_path and Path(s.bgm_path).exists()
    if use_bgm:
        inputs += ["-stream_loop", "-1", "-i", str(s.bgm_path)]
        bgm_i = next_i
        next_i += 1

    # 필터 그래프
    if use_overlay:
        graph = f"[0:v][{ov_i}:v]overlay=0:0:format=auto,format=yuv420p[v];"
    else:
        graph = "[0:v]format=yuv420p,setsar=1[v];"

    narr = f"[{narr_i}:a]"
    if use_bgm:
        graph += f"[{bgm_i}:a]atrim=0:{dur:.4f},asetpts=PTS-STARTPTS,volume={s.bgm_volume:.3f}[bg];"
        if s.duck_bgm:
            graph += (
                f"[bg]{narr}sidechaincompress=threshold=0.02:ratio=8:attack=25:release=400:makeup=1[bgd];"
                f"{narr}[bgd]amix=inputs=2:duration=first:normalize=0[a]"
            )
        else:
            graph += f"{narr}[bg]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        graph += f"{narr}anull[a]"

    audio_label = "a"
    if s.loudnorm:
        graph += ";[a]loudnorm=I=-14:TP=-1.5:LRA=11[ao]"
        audio_label = "ao"

    run(
        [
            ffmpeg, "-y", *inputs,
            "-filter_complex", graph,
            "-map", "[v]", "-map", f"[{audio_label}]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", "-t", f"{dur:.4f}",
            str(s.final_path),
        ],
        desc="최종 먹스(faststart, 쇼츠 업로드 최적화)",
    )
    log(f"✅ 최종 영상: {s.final_path} ({s.final_path.stat().st_size//1024} KB, {dur:.2f}s)")
    return s.final_path

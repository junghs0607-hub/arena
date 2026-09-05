"""나레이션 생성(TTS) + 씬별 오디오를 하나의 마스터 트랙으로 합성.

백엔드 우선순위(auto): edge-tts → gTTS.
  * edge-tts: 묻지도 따지지도 않는 고품질 한국어 신경망 음성(묣롬).
  * gTTS:    가볍지만 음질 낮음 (최후의 평활 수단).
각 씬 오디오는 개별 mp3로 저장되고, 나중에 타임라인의 씬 길이에 딱 맞게
뒤에 무음을 붙여(apad/atrim) concatenation → 나레이션 마스터 WAV.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from .common import fail, find_binary, log, run, warn
from .config import Settings
from .media_utils import probe_duration


# ── TTS 백엔드 ─────────────────────────────────────────

async def _edge_say(text: str, out: Path, voice: str, rate: str) -> None:
    import edge_tts  # 지연 import (설치 안 된 환경 대비)

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(out))


def _gtts_say(text: str, out: Path) -> None:
    from gtts import gTTS  # type: ignore

    gTTS(text=text, lang="ko").save(str(out))


def synthesize_scene(text: str, out: Path, s: Settings) -> None:
    """한 씬의 나레이션을 mp3로 저장. 백엔드 자동 평활."""
    backends = {
        "edge": lambda: asyncio.run(_edge_say(text, out, s.voice, s.rate)),
        "gtts": lambda: _gtts_say(text, out),
    }
    order = ["edge", "gtts"] if s.tts_backend == "auto" else [s.tts_backend]

    last_err: Exception | None = None
    for name in order:
        try:
            backends[name]()
            if out.exists() and out.stat().st_size > 0:
                log(f"  TTS[{name}] -> {out.name} ({out.stat().st_size//1024} KB)")
                return
            raise RuntimeError("빈 파일 생성됨")
        except Exception as e:  # noqa: BLE001
            last_err = e
            warn(f"TTS 백엔드 '{name}' 실패: {e}")
    fail(f"모든 TTS 백엔드 실패. 마지막 오류: {last_err}")


_PRERECORDED_EXTS = [".mp3", ".wav", ".m4a", ".aac", ".ogg"]


def _find_prerecorded(s: Settings, index: int) -> Path | None:
    """사용자가 미리 녹음/다운로드해 둔 나레이션(scene_XX.mp3 등)을 찾는다.

    다른 TTS/직접 녹음 등 외부에서 만든 목소리를 쓰고 싶을 때:
      assets/narration/scene_00.mp3, scene_01.mp3 ... 형태로 넣으면 TTS 생략.
    """
    if not s.narration_dir:
        return None
    d = Path(s.narration_dir)
    for ext in _PRERECORDED_EXTS:
        cand = d / f"scene_{index:02d}{ext}"
        if cand.exists() and cand.stat().st_size > 0:
            return cand
    return None


def synthesize_all(texts: list[str], s: Settings) -> list[Path]:
    import shutil

    s.audio_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, text in enumerate(texts):
        out = s.audio_dir / f"scene_{i:02d}.mp3"
        pre = _find_prerecorded(s, i)
        if pre is not None:
            if pre.resolve() != out.resolve():
                shutil.copy2(pre, out)
            log(f"  사전 녹음 나레이션 사용: {pre.name} (TTS 생략)")
        elif out.exists() and out.stat().st_size > 0:
            log(f"  TTS 캐시 재사용: {out.name}")
        else:
            synthesize_scene(text, out, s)
        paths.append(out)
    return paths


# ── 나레이션 마스터 트랙 ────────────────────────────────

def build_narration_track(
    scene_audios: list[Path], scene_durations: list[float], s: Settings
) -> Path:
    """씬 오디오 뒤에 무음을 붙여 씬 길이에 정확히 맞춘 뒤 이어 붙인다.

    이렇게 하면 "씬 시작 시각 = 씬 오디오 시작 시각"이 보장되어
    자막/영상/나레이션이 프레임 단위로 정렬된다.
    """
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        fail("ffmpeg를 찾을 수 없습니다.")

    pad_dir = s.work_dir / "audio_padded"
    pad_dir.mkdir(parents=True, exist_ok=True)
    padded: list[Path] = []
    for i, (src, dur) in enumerate(zip(scene_audios, scene_durations)):
        out = pad_dir / f"pad_{i:02d}.wav"
        run(
            [
                ffmpeg, "-y", "-i", str(src),
                "-af", f"apad,atrim=0:{dur:.4f}",
                "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out),
            ],
            desc=f"씬 {i} 오디오 패딩 ({dur:.2f}s)",
        )
        padded.append(out)

    list_file = s.work_dir / "narration_concat.txt"
    list_file.write_text(
        "".join(f"file '{p.resolve()}'\n" for p in padded), encoding="utf-8"
    )
    run(
        [
            ffmpeg, "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c", "copy", str(s.narration_path),
        ],
        desc="나레이션 마스터 트랙 concat",
    )
    total = probe_duration(s.narration_path)
    log(f"  narration_full.wav = {total:.3f}s")
    return s.narration_path


def audio_durations(paths: list[Path]) -> list[float]:
    return [probe_duration(p) for p in paths]

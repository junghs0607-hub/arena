"""나레이션 생성(TTS) + 씬별 오디오를 하나의 마스터 트랙으로 합성.

백엔드 (auto 기본 순서: qwen → edge → gtts, `--tts-backend "qwen,edge"`처럼 체인 지정):
  * qwen : Qwen3-TTS 로컬 추론 (pip install qwen-tts, GPU 권장).
           한국어 프리셋 Sohee, 톤 지시(instruct)/보이스 클론 지원, 생성 시 네트워크 불필요.
           최초 1회만 모델 가중치 다운로드(수 GB).
  * edge : 고품질 한국어 신경망 클라우드 음성 (묻지도 따지지도 않는 무료).
  * gtts : 가볍지만 음질 낮음 (최후의 평활 수단).
각 씬 오디오는 개별 mp3로 저장되고, 나중에 타임라인의 씬 길이에 딱 맞게
뒤에 무음을 붙여(apad/atrim) concatenation → 나레이션 마스터 WAV.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from .common import fail, find_binary, log, run, warn
from .config import Settings
from .media_utils import probe_duration


# ── TTS 백엔드: edge-tts / gTTS ───────────────────────

async def _edge_say(text: str, out: Path, voice: str, rate: str) -> None:
    import edge_tts  # 지연 import (설치 안 된 환경 대비)

    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(str(out))


def _gtts_say(text: str, out: Path) -> None:
    from gtts import gTTS  # type: ignore

    gTTS(text=text, lang="ko").save(str(out))


# ── TTS 백엔드: Qwen3-TTS (로컬) ──────────────────────

_qwen_cache: dict = {}  # (model,device) -> model / ("clone",ref,text) -> clone prompt


def _qwen_device(s: Settings) -> str:
    if s.qwen_device != "auto":
        return s.qwen_device
    import torch

    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _qwen_load(s: Settings):
    key = (s.qwen_model, _qwen_device(s))
    if key in _qwen_cache:
        return _qwen_cache[key]
    import torch
    from qwen_tts import Qwen3TTSModel  # 지연 import — 미설치 시 다음 백엔드로 평활

    dev = key[1]
    dtype = torch.bfloat16 if dev.startswith("cuda") else torch.float32
    log(f"  Qwen3-TTS 로드: {s.qwen_model} ({dev}, {dtype})")
    log("  ※ 최초 실행 시 모델 가중치 다운로드(수 GB, Hugging Face)")
    model = Qwen3TTSModel.from_pretrained(s.qwen_model, device_map=dev, dtype=dtype)
    _qwen_cache[key] = model
    return model


def _qwen_clone_prompt(model, s: Settings):
    key = ("clone", str(s.qwen_ref_audio), s.qwen_ref_text)
    if key not in _qwen_cache:
        log(f"  보이스 클론 프롬프트 생성: {s.qwen_ref_audio}")
        _qwen_cache[key] = model.create_voice_clone_prompt(
            ref_audio=str(s.qwen_ref_audio),
            ref_text=s.qwen_ref_text or None,
        )
    return _qwen_cache[key]


def _qwen_say(text: str, out: Path, s: Settings) -> None:
    """Qwen3-TTS 생성(wav) → ffmpeg로 mp3 변환(파이프라인 표준 입력 포맷)."""
    import soundfile as sf

    model = _qwen_load(s)
    name = s.qwen_model.lower()

    if "customvoice" in name:
        kwargs = {"instruct": s.qwen_instruct} if s.qwen_instruct else {}
        wavs, sr = model.generate_custom_voice(
            text=text, language=s.qwen_language, speaker=s.qwen_speaker, **kwargs
        )
    elif "voicedesign" in name:
        if not s.qwen_instruct:
            raise RuntimeError("VoiceDesign 모델은 --qwen-instruct(목소리 지시)가 필요합니다.")
        wavs, sr = model.generate_voice_design(
            text=text, language=s.qwen_language, instruct=s.qwen_instruct
        )
    else:  # Base → 보이스 클론 (레퍼런스 음성 필요)
        if not s.qwen_ref_audio or not Path(s.qwen_ref_audio).exists():
            raise RuntimeError(
                "Base 모델(보이스 클론)은 --qwen-ref-audio 레퍼런스 음성(3초 이상)이 필요합니다."
            )
        wavs, sr = model.generate_voice_clone(
            text=text,
            language=s.qwen_language,
            voice_clone_prompt=_qwen_clone_prompt(model, s),
        )

    tmp = out.with_suffix(".qwen.wav")
    sf.write(str(tmp), wavs[0], sr)
    ffmpeg = find_binary("ffmpeg")
    if ffmpeg:
        run(
            [ffmpeg, "-y", "-i", str(tmp), "-codec:a", "libmp3lame", "-q:a", "3", str(out)],
            desc="Qwen wav → mp3 변환",
        )
        tmp.unlink(missing_ok=True)
    else:  # ffmpeg마저 없는 극단 상황: wav 그대로 사용(다운스트림에서도 자동 인식)
        tmp.rename(out)


# ── 백엔드 체인 ───────────────────────────────────────

def _backend_order(spec: str) -> list[str]:
    if spec == "auto":
        return ["qwen", "edge", "gtts"]  # qwen-tts 미설치 환경에서는 즉시 다음으로
    return [x.strip() for x in spec.split(",") if x.strip()]


def synthesize_scene(text: str, out: Path, s: Settings) -> None:
    """한 씬의 나레이션을 mp3로 저장. 지정 체인을 순회하며 평활."""
    backends = {
        "qwen": lambda: _qwen_say(text, out, s),
        "edge": lambda: asyncio.run(_edge_say(text, out, s.voice, s.rate)),
        "gtts": lambda: _gtts_say(text, out),
    }
    order = _backend_order(s.tts_backend)

    last_err: Exception | None = None
    for name in order:
        fn = backends.get(name)
        if fn is None:
            fail(f"알 수 없는 TTS 백엔드: {name} (가능: qwen/edge/gtts/auto)")
        try:
            fn()
            if out.exists() and out.stat().st_size > 0:
                log(f"  TTS[{name}] -> {out.name} ({out.stat().st_size//1024} KB)")
                return
            raise RuntimeError("빈 파일 생성됨")
        except Exception as e:  # noqa: BLE001
            last_err = e
            warn(f"TTS 백엔드 '{name}' 실패: {str(e)[:300]}")
    fail(f"모든 TTS 백엔드 실패(체인: {order}). 마지막 오류: {last_err}")


# ── 사전 녹음 나레이션 재사용 ──────────────────────────

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

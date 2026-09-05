"""파이프라인 전역 설정.

CLI(build.py)에서 인자를 받아 이 dataclass 하나로 모든 단계에 전달한다.
경로만 바꾸면 다른 프로젝트(다른 쇼츠)에도 재사용 가능하다.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    # ── 경로 ─────────────────────────────────────────────
    script_path: Path          # 대본(txt)
    media_dir: Path            # 직접 생성/다운로드한 이미지/비디오
    work_dir: Path             # 중간 산출물(오디오, 세그먼트, 타임라인 등)
    out_dir: Path              # 최종 결과물
    bgm_path: Path | None = None
    narration_dir: Path | None = None  # 사전 녹음 나레이션(scene_XX.mp3) 재사용 폴더

    # ── 영상 규격 (쇼츠/릴스/틱톡 9:16) ──────────────────
    width: int = 1080
    height: int = 1920
    fps: int = 30

    # ── TTS (나레이션) ──────────────────────────────────
    # edge-tts 한국어 음성 예시:
    #   여성 ko-KR-SunHiNeural(기본), ko-KR-JiMinNeural
    #   남성 ko-KR-InJoonNeural, ko-KR-HyunsuNeural
    voice: str = "ko-KR-SunHiNeural"
    rate: str = "+6%"                     # 말하기 속도 (예: "-10%", "+0%")
    tts_backend: str = "auto"             # auto | qwen | edge | gtts (콤마로 체인 가능: "qwen,edge")

    # ── Qwen3-TTS (로컬 고품질 TTS, 한국어 Sohee 프리셋) ──
    # 모델 예시:
    #   Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice  (기본, 9개 프리셋+지시 제어)
    #   Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice  (경량)
    #   Qwen/Qwen3-TTS-12Hz-1.7B-Base         (레퍼런스 음성으로 보이스 클론)
    #   Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign  (텍스트 지시로 목소리 설계)
    qwen_model: str = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    qwen_speaker: str = "Sohee"           # 한국어 여성 프리셋
    qwen_language: str = "Korean"
    qwen_device: str = "auto"             # auto | cpu | cuda:0 ...
    qwen_instruct: str = ""               # 톤 지시 (예: "차분하고 신뢰감 있는 낭독")
    qwen_ref_audio: Path | None = None    # Base(보이스 클론)용 레퍼런스 음성 (3초+)
    qwen_ref_text: str = ""               # 레퍼런스 음성의 대사(클론 정확도 향상)

    # ── Whisper (자막 타이밍) ────────────────────────────
    use_whisper: bool = True
    whisper_model: str = "base"           # tiny/base/small/medium/large-v3
    whisper_device: str = "auto"          # cpu / cuda / auto

    # ── 타이밍 ───────────────────────────────────────────
    scene_padding: float = 0.40           # 씬 끝 여백(초). 호흡/전환용

    # ── 오디오 믹스 ─────────────────────────────────────
    bgm_volume: float = 0.20              # BGM 기본 음량 (0~1)
    duck_bgm: bool = True                 # 나레이션 중 BGM 자동 줄이기
    loudnorm: bool = False                # 최종 믹스에 EBU R128 라우드니스 정규화

    # ── 자막/그래픽 ─────────────────────────────────────
    watermark: str = ""                   # 상단 워터마크 텍스트 (빈 문자열이면 숨김)

    # ── Remotion 오버레이 렌더 ──────────────────────────
    overlay_codec: str = "vp9"            # vp9(알파 WebM) | prores(알파 MOV, 무손실급)
    use_overlay: bool = True              # False면 Remotion 없이 급속 미리보기 조립

    def ensure_dirs(self) -> None:
        for d in (self.work_dir, self.out_dir, self.media_dir):
            Path(d).mkdir(parents=True, exist_ok=True)

    # 자주 쓰는 파생 경로
    @property
    def timeline_path(self) -> Path:
        return self.work_dir / "timeline.json"

    @property
    def prep_path(self) -> Path:
        return self.work_dir / "prep.json"

    @property
    def audio_dir(self) -> Path:
        return self.work_dir / "audio"

    @property
    def segments_dir(self) -> Path:
        return self.work_dir / "segments"

    @property
    def base_video_path(self) -> Path:
        return self.work_dir / "base.mp4"

    @property
    def narration_path(self) -> Path:
        return self.work_dir / "narration_full.wav"

    @property
    def overlay_path(self) -> Path:
        return self.work_dir / ("overlay.webm" if self.overlay_codec == "vp9" else "overlay.mov")

    @property
    def final_path(self) -> Path:
        return self.out_dir / "final.mp4"

    @property
    def srt_path(self) -> Path:
        return self.out_dir / "subtitles.srt"

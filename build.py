#!/usr/bin/env python3
"""반자동 쇼츠 조립 시스템 — 오케스트레이터.

사용:
  python build.py all                 # 대본→나레이션→자막→Remotion→최종조립 전체
  python build.py audio               # 나레이션(TTS)까지만
  python build.py subs                # 자막 타이밍(Whisper)만 재실행
  python build.py base|overlay|mux    # 조립 단계만 개별 실행
  python build.py all --no-whisper    # Whisper 없이 비례 배분 자막
  python build.py all --bgm assets/bgm/lofi.mp3 --watermark "@mychannel"

데이터 흐름 (각 단계는 work/ 아래 중간 산출물로 이어짐):
  script.txt → [prepare] prep.json → [audio] 씬별 mp3 → [timeline] timeline.json
  → [subs] timeline.json(subtitles) + subtitles.srt
  → [base] base.mp4 → [overlay] overlay.webm → [mux] output/final.mp4
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.config import Settings
from pipeline.common import log, fail
from pipeline.script_parser import parse_script
from pipeline.media_utils import collect_media, match_scenes_to_media
from pipeline import narration as tts
from pipeline import timeline as tl
from pipeline import timestamps as ts
from pipeline import base_video as bv
from pipeline import remotion_render as rr
from pipeline import mux as mx
from pipeline import scriptgen as sg


# ── AI 대본 생성 (관리자 프롬프트 + 주제) ────────────────

def stage_scriptgen(args: argparse.Namespace) -> None:
    """주제 → 씬 팩(대본 + 이미지/동영상 프롬프트) 생성."""
    if not args.topic:
        fail("`--topic \"주제\"`를 입력하세요.")
    try:
        pack = sg.generate_scene_pack(
            args.topic,
            scenes=args.scenes,
            duration=args.duration,
            tone=args.tone,
            media_lang=args.media_lang,
            prompt_path=args.pack_prompt_file,
            llm_path=args.llm_config,
        )
    except sg.ScriptGenError as e:
        fail(str(e))
        return
    script_text = pack.to_script()
    sg.save_script(script_text, args.script)
    prompts_prefix = Path(args.out_dir) / "media_prompts"
    sg.save_scene_pack(pack, prompts_prefix)

    print("\n──────── 생성된 대본 미리보기 ────────")
    print(script_text)
    print("──────── 시각 프롬프트(씬 1 예시) ────────")
    first = pack.scenes[0]
    print(f"[이미지] {first.image_prompt or '(없음)'}")
    print(f"[영상] {first.video_prompt or '(없음)'}")
    print("─────────────────────────────────────")
    log(f"영상/이미지 생성 툴에서 미디어 생성 → {args.media_dir} 에 넣은 뒤 `python build.py all`")
    log(f"전체 프롬프트: {prompts_prefix.with_suffix('.txt')}")


def stage_mediaprompts(args: argparse.Namespace) -> None:
    """완성된 대본(직접 입력/외부 AI) → 씬별 이미지/동영상 프롬프트."""
    from pipeline.script_parser import parse_script

    scenes = parse_script(Path(args.script))
    if not scenes:
        fail(f"대본이 비어 있습니다: {args.script}")
    texts = [sc.text for sc in scenes]
    try:
        prompts = sg.generate_media_prompts(
            texts,
            media_lang=args.media_lang,
            prompt_path=args.media_prompt_file,
            llm_path=args.llm_config,
        )
    except sg.ScriptGenError as e:
        fail(str(e))
        return
    pack = sg.ScenePack(prompts)
    prompts_prefix = Path(args.out_dir) / "media_prompts"
    sg.save_scene_pack(pack, prompts_prefix)
    print(pack.to_prompts_text())
    log(f"전체 프롬프트: {prompts_prefix.with_suffix('.txt')}")


# ── 단계 구현 ──────────────────────────────────────────

def stage_prepare(s: Settings) -> list[dict]:
    scenes = parse_script(s.script_path)
    if not scenes:
        fail(f"대본이 비어 있습니다: {s.script_path}")
    log(f"대본 {len(scenes)}씬 로드: {s.script_path}")
    media = collect_media(s.media_dir)
    mm = match_scenes_to_media(scenes, media)
    prep = {
        "scenes": [sc.to_dict() for sc in scenes],
        "media": [m.to_dict() for m in mm],
    }
    s.prep_path.write_text(json.dumps(prep, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"씬↔미디어 매칭 완료 -> {s.prep_path}")
    return [sc.to_dict() for sc in scenes]


def load_prep(s: Settings) -> dict:
    if not s.prep_path.exists():
        fail(f"{s.prep_path} 없음. 먼저 `python build.py prepare` (또는 all)를 실행하세요.")
    return json.loads(s.prep_path.read_text(encoding="utf-8"))


def stage_audio(s: Settings) -> tuple[list[Path], list[float]]:
    prep = load_prep(s)
    texts = [sc["text"] for sc in prep["scenes"]]
    paths = tts.synthesize_all(texts, s)
    durs = tts.audio_durations(paths)
    for i, d in enumerate(durs):
        log(f"  씬 {i} 나레이션: {d:.2f}s")
    prep["audio"] = [str(p) for p in paths]
    prep["audio_durations"] = durs
    s.prep_path.write_text(json.dumps(prep, ensure_ascii=False, indent=2), encoding="utf-8")
    return paths, durs


def stage_timeline(s: Settings) -> dict:
    prep = load_prep(s)
    from pipeline.script_parser import Scene
    from pipeline.media_utils import MediaInfo

    scenes = [Scene(index=d["index"], text=d["text"], sentences=d["sentences"]) for d in prep["scenes"]]
    media = [
        MediaInfo(path=Path(m["path"]), kind=m["kind"], duration=m["duration"], width=m["width"], height=m["height"])
        for m in prep["media"]
    ]
    audios = [Path(a) for a in prep["audio"]]
    durs = prep["audio_durations"]
    timeline = tl.build_timeline(scenes, media, audios, durs, s)
    scene_durs = [sc["duration"] for sc in timeline["scenes"]]
    tts.build_narration_track(audios, scene_durs, s)
    return timeline


def stage_subs(s: Settings) -> dict:
    return ts.run_timestamps(s)


def stage_base(s: Settings) -> Path:
    timeline = tl.load_timeline(s)
    return bv.build_base(timeline, s)


def stage_overlay(s: Settings) -> Path:
    timeline = tl.load_timeline(s)
    return rr.render_overlay(s, timeline)


def stage_mux(s: Settings) -> Path:
    timeline = tl.load_timeline(s)
    return mx.mux_final(timeline, s)


def stage_all(s: Settings) -> None:
    steps: list[tuple[str, callable]] = [
        ("prepare — 대본 파싱 + 미디어 매칭", lambda: stage_prepare(s)),
        ("audio — 나레이션 TTS", lambda: stage_audio(s)),
        ("timeline — 타임라인 + 나레이션 마스터", lambda: stage_timeline(s)),
        ("subs — 자막 타이밍", lambda: stage_subs(s)),
        ("base — FFmpeg 베이스 조립", lambda: stage_base(s)),
    ]
    if s.use_overlay:
        steps.append(("overlay — Remotion 그래픽 렌더", lambda: stage_overlay(s)))
    steps.append(("mux — 최종 조립", lambda: stage_mux(s)))

    for i, (label, fn) in enumerate(steps, 1):
        log(f"━━ {i}/{len(steps)} {label} ━━")
        fn()
    log(f"🎬 완료: {s.final_path}")


# ── CLI ────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="반자동 쇼츠 조립 시스템",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("stage", choices=["prepare", "audio", "timeline", "subs", "base", "overlay", "mux", "all", "scriptgen", "mediaprompts"],
                   help="scriptgen: 주제→대본+미디어프롬프트 / mediaprompts: 기존 대본→미디어프롬프트")
    p.add_argument("--script", default="assets/script.txt", help="대본(txt). 빈 줄로 씬 구분 (scriptgen 출력 경로 겸용)")
    p.add_argument("--media-dir", default="assets/media", help="생성한 이미지/비디오 폴더")
    p.add_argument("--work-dir", default="work", help="중간 산출물 폴더")
    p.add_argument("--out-dir", default="output", help="최종 산출물 폴더")
    p.add_argument("--bgm", default=None, help="배경음악 파일(mp3/wav)")
    p.add_argument("--narration-dir", default="assets/narration", help="사전 녹음 나레이션 폴더 (scene_XX.mp3 있으면 TTS 생략)")
    p.add_argument("--voice", default="ko-KR-SunHiNeural", help="edge-tts 음성 (남성: ko-KR-InJoonNeural)")
    p.add_argument("--rate", default="+6%", help="말하기 속도 (예: -10%%, +10%%)")
    p.add_argument("--tts-backend", default="auto",
                   help="엔진: auto | qwen | edge | gtts (콤마 체인: 'qwen,edge')")
    # ── Qwen3-TTS (로컬 고품질) ──
    p.add_argument("--qwen-model", default="Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
                   help="Qwen3-TTS 모델 id (경량: ...-0.6B-CustomVoice, 클론: ...-Base)")
    p.add_argument("--qwen-speaker", default="Sohee", help="프리셋 스피커 (한국어: Sohee)")
    p.add_argument("--qwen-language", default="Korean")
    p.add_argument("--qwen-device", default="auto", help="auto | cpu | cuda:0")
    p.add_argument("--qwen-instruct", default="", help="톤 지시 (예: '차분하고 신뢰감 있는 낭독')")
    p.add_argument("--qwen-ref-audio", default=None, help="보이스 클론 레퍼런스 음성 (Base 모델용, 3초+)")
    p.add_argument("--qwen-ref-text", default="", help="레퍼런스 음성의 대사")
    p.add_argument("--no-whisper", action="store_true", help="Whisper 대신 문장 길이 비례 자막 사용")
    p.add_argument("--whisper-model", default="base", help="tiny/base/small/medium/large-v3")
    p.add_argument("--whisper-device", default="auto", choices=["auto", "cpu", "cuda"])
    p.add_argument("--padding", type=float, default=0.40, help="씬 끝 여백(초)")
    p.add_argument("--bgm-volume", type=float, default=0.20)
    p.add_argument("--no-duck", action="store_true", help="BGM 덕킹 끄기")
    p.add_argument("--loudnorm", action="store_true", help="최종 믹스 라우드니스 정규화(-14 LUFS)")
    p.add_argument("--watermark", default="", help="상단 워터마크 텍스트")
    p.add_argument("--overlay-codec", default="vp9", choices=["vp9", "prores"])
    p.add_argument("--no-overlay", action="store_true", help="Remotion 오버레이 생략(급속 미리보기)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    # ── AI 대본 생성(scriptgen) ──
    p.add_argument("--topic", default=None, help="대본 주제 (scriptgen 전용)")
    p.add_argument("--scenes", type=int, default=4, help="씬 개수")
    p.add_argument("--duration", type=int, default=30, help="목표 낭독 초")
    p.add_argument("--tone", default="정보 전달·실용 꿀팁", help="톤/장르 지시")
    p.add_argument("--prompt-file", default="admin/script_prompt.txt", help="관리자 프롬프트 템플릿(대본 전용 레거시)")
    p.add_argument("--pack-prompt-file", default="admin/scene_pack_prompt.txt", help="씬 팩(대본+시각프롬프트) 템플릿")
    p.add_argument("--media-prompt-file", default="admin/media_prompt.txt", help="미디어 프롬프트 전용 템플릿")
    p.add_argument("--media-lang", default="English", help="이미지/영상 프롬프트 언어")
    p.add_argument("--llm-config", default="admin/llm.json", help="LLM 연결 설정 JSON")
    return p


def make_settings(args: argparse.Namespace) -> Settings:
    s = Settings(
        script_path=Path(args.script),
        media_dir=Path(args.media_dir),
        work_dir=Path(args.work_dir),
        out_dir=Path(args.out_dir),
        bgm_path=Path(args.bgm) if args.bgm else None,
        narration_dir=Path(args.narration_dir) if args.narration_dir else None,
        voice=args.voice,
        rate=args.rate,
        tts_backend=args.tts_backend,
        qwen_model=args.qwen_model,
        qwen_speaker=args.qwen_speaker,
        qwen_language=args.qwen_language,
        qwen_device=args.qwen_device,
        qwen_instruct=args.qwen_instruct,
        qwen_ref_audio=Path(args.qwen_ref_audio) if args.qwen_ref_audio else None,
        qwen_ref_text=args.qwen_ref_text,
        use_whisper=not args.no_whisper,
        whisper_model=args.whisper_model,
        whisper_device=args.whisper_device,
        scene_padding=args.padding,
        bgm_volume=args.bgm_volume,
        duck_bgm=not args.no_duck,
        loudnorm=args.loudnorm,
        watermark=args.watermark,
        overlay_codec=args.overlay_codec,
        use_overlay=not args.no_overlay,
        fps=args.fps,
        width=args.width,
        height=args.height,
    )
    s.ensure_dirs()
    return s


def main() -> None:
    args = build_parser().parse_args()
    if args.stage == "scriptgen":
        stage_scriptgen(args)
        return
    if args.stage == "mediaprompts":
        stage_mediaprompts(args)
        return
    s = make_settings(args)
    stages = {
        "prepare": lambda: stage_prepare(s),
        "audio": lambda: stage_audio(s),
        "timeline": lambda: stage_timeline(s),
        "subs": lambda: stage_subs(s),
        "base": lambda: stage_base(s),
        "overlay": lambda: stage_overlay(s),
        "mux": lambda: stage_mux(s),
        "all": lambda: stage_all(s),
    }
    stages[args.stage]()


if __name__ == "__main__":
    sys.exit(main())

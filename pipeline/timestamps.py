"""Whisper 기반 자막 타이밍 추출 + 대본 정렬(forced alignment with script).

전략:
  1) 씬별 오디오(mp3)를 faster-whisper + word_timestamps 로 전사
     (전체 파일이 아니라 씬 단위로 돌려 드리프트를 원천 차단하고,
      절대시각 = scene.start + 상대시각 으로 복원)
  2) 대본의 '문장'과 Whisper의 '단어'를 정규화 문자 매칭으로 정렬해
     "자막 문장의 [start, end]"를 얻는다 → 자막 텍스트는 대본과 100% 일치.
  3) 문장 안 표시 토큰(공백 분리)마다 시각을 배정해 karaoke 하이라이트 지원.
  4) Whisper 자체가 없거나 실패하면 문장 글자수 비례 배분으로 평활.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .common import log, warn
from .config import Settings
from .timeline import load_timeline, save_timeline

_NORM_RE = re.compile(r"[^0-9A-Za-z가-힣ㄱ-ㅎㅏ-ㅣ]")


def normalize(text: str) -> str:
    return _NORM_RE.sub("", text).lower()


# ── Whisper 전사 ───────────────────────────────────────

_model_cache: dict[str, object] = {}


def _get_model(model_size: str, device: str):
    key = f"{model_size}:{device}"
    if key not in _model_cache:
        from faster_whisper import WhisperModel  # 지연 import

        dev = device if device != "auto" else "auto"
        compute = "int8" if dev in ("cpu", "auto") else "float16"
        log(f"  Whisper 모델 로드: {model_size} (device={dev}, {compute})")
        _model_cache[key] = WhisperModel(model_size, device=dev, compute_type=compute)
    return _model_cache[key]


def transcribe_words(audio: Path, s: Settings) -> list[dict]:
    """한 씬 오디오에서 [{start, end, text}] 단어 목록(상대 시각)."""
    model = _get_model(s.whisper_model, s.whisper_device)
    segments, _ = model.transcribe(
        str(audio), language="ko", word_timestamps=True, vad_filter=True
    )
    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            words.append({"start": float(w.start), "end": float(w.end), "text": w.word})
    return words


# ── 대본 문장 ↔ 단어 정렬 ───────────────────────────────

def align_sentences(
    sentences: list[str], words: list[dict], start_offset: float, scene_dur: float
) -> list[dict]:
    """Whisper 단어를 문장에 탐욕 할당해 문장 [start,end]를 복원한다."""
    if not sentences:
        return []
    if not words:
        return proportional(sentences, start_offset, scene_dur)

    subs: list[dict] = []
    wi = 0
    n = len(words)
    for k, sent in enumerate(sentences):
        target = normalize(sent)
        if wi >= n:  # 단어가 모자라면 남은 문장은 비례 배분
            head = subs[-1]["end"] if subs else start_offset
            tail = proportional(sentences[k:], start_offset, scene_dur, head=head)
            return subs + tail

        s_word = words[wi]
        sent_start = s_word["start"]
        acc = ""
        sent_words: list[dict] = []
        # 목표 글자를 덮을 때까지 단어를 흡수 (조금 넘치는 것 허용)
        while wi < n and (not acc or len(acc) < len(target)):
            w = words[wi]
            sent_words.append(w)
            acc += normalize(w["text"])
            wi += 1
            if target and normalize(target)[: len(acc)] != acc[: len(normalize(target))]:
                # 앞글자부터 어긋나면(전사 불일치) 글자수 기준으로만 진행
                if len(acc) >= len(target):
                    break
            if target and acc[: len(target)] == target[: len(acc)] and len(acc) >= len(target):
                break
        sent_end = sent_words[-1]["end"]
        subs.append(
            {
                "start": round(start_offset + max(0.0, sent_start), 3),
                "end": round(start_offset + max(sent_start + 0.05, sent_end), 3),
                "text": sent,
                "words": [
                    {
                        "start": round(start_offset + w["start"], 3),
                        "end": round(start_offset + w["end"], 3),
                        "text": w["text"].strip(),
                    }
                    for w in sent_words
                ],
            }
        )
    # 겹침/역전 방어: 시간 단조 증가 보정
    for i in range(1, len(subs)):
        subs[i]["start"] = max(subs[i]["start"], subs[i - 1]["end"])
        subs[i]["end"] = max(subs[i]["end"], subs[i]["start"] + 0.05)
    return _assign_tokens_all([], subs)


def proportional(
    sentences: list[str], start_offset: float, duration: float, head: float | None = None
) -> list[dict]:
    """Whisper 없이 문장 글자수 비례로 시각 배분(평활 경로)."""
    base = head if head is not None else start_offset
    remain = (start_offset + duration) - base
    weights = [max(1, len(normalize(t))) for t in sentences]
    total = sum(weights)
    subs: list[dict] = []
    cursor = base
    for t, w in zip(sentences, weights):
        dur = remain * (w / total)
        subs.append(
            {
                "start": round(cursor, 3),
                "end": round(cursor + dur, 3),
                "text": t,
                "words": [],
            }
        )
        cursor += dur
    return _assign_tokens_all([], subs)


def _assign_tokens_all(acc: list[dict], subs: list[dict]) -> list[dict]:
    """각 자막 문장에 표시 토큰(공백 단위) 시각을 심는다 (karaoke용)."""
    for sub in subs:
        tokens = [t for t in re.split(r"(\s+)", sub["text"]) if t.strip()]
        words = sub.get("words") or []
        if words and tokens:
            w0, w1 = words[0]["start"], words[-1]["end"]
            n_tok, n_w = len(tokens), len(words)
            out_tokens = []
            for j, tok in enumerate(tokens):
                # 토큰 j ↔ 단어 floor(j*N/M) 매핑으로 whisper 단어 시각 활용
                wi = min(n_w - 1, (j * n_w) // n_tok)
                w_next = min(n_w - 1, ((j + 1) * n_w) // n_tok)
                out_tokens.append(
                    {
                        "text": tok,
                        "start": round(words[wi]["start"], 3),
                        "end": round(max(words[w_next]["end"], words[wi]["start"] + 0.05), 3),
                    }
                )
            sub["tokens"] = out_tokens
        else:
            # 단어 정보가 없으면 시간을 토큰에 균등 분배
            span = (sub["end"] - sub["start"]) / max(1, len(tokens))
            sub["tokens"] = [
                {
                    "text": tok,
                    "start": round(sub["start"] + j * span, 3),
                    "end": round(sub["start"] + (j + 1) * span, 3),
                }
                for j, tok in enumerate(tokens)
            ]
        sub.pop("words", None)
    return acc + subs


# ── 파이프라인 단계 ────────────────────────────────────

def run_timestamps(s: Settings) -> dict:
    timeline = load_timeline(s)
    all_subs: list[dict] = []

    whisper_ok = s.use_whisper
    if whisper_ok:
        try:
            import faster_whisper  # noqa: F401
        except Exception as e:
            warn(f"faster-whisper 사용 불가({e}). 비례 배분 자막으로 대체합니다.")
            whisper_ok = False

    for scene in timeline["scenes"]:
        if whisper_ok:
            try:
                words = transcribe_words(Path(scene["audio"]), s)
                log(f"  씬 {scene['index']}: Whisper 단어 {len(words)}개")
                sub = align_sentences(
                    scene["sentences"], words, scene["start"], scene["duration"]
                )
            except Exception as e:  # noqa: BLE001
                warn(f"씬 {scene['index']} Whisper 실패({e}). 비례 배분으로 대체.")
                sub = proportional(scene["sentences"], scene["start"], scene["duration"])
        else:
            sub = proportional(scene["sentences"], scene["start"], scene["duration"])
        for item in sub:
            item["scene"] = scene["index"]
        all_subs.extend(sub)

    timeline["subtitles"] = all_subs
    save_timeline(timeline, s)
    write_srt(all_subs, s.srt_path)
    log(f"자막 {len(all_subs)}문장 -> timeline.json 갱신, {s.srt_path}")
    return timeline


# ── SRT 출력 ───────────────────────────────────────────

def _fmt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def write_srt(subs: list[dict], path: Path) -> None:
    blocks = []
    for i, sub in enumerate(subs, 1):
        blocks.append(f"{i}\n{_fmt(sub['start'])} --> {_fmt(sub['end'])}\n{sub['text']}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(blocks), encoding="utf-8")


def load_subtitles_only(s: Settings) -> list[dict]:
    return json.loads(s.timeline_path.read_text(encoding="utf-8")).get("subtitles", [])

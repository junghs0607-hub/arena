#!/usr/bin/env python3
"""네트워크/TTS/Whisper 없이 돌아가는 결정적 단위 테스트.

실행:
  python tests/test_pipeline.py        (pytest 없이 직접 실행)
  python -m pytest tests/              (pytest 사용 시)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.script_parser import parse_script, split_sentences
from pipeline.timeline import quantize_to_frames
from pipeline.timestamps import align_sentences, normalize, proportional


# ── 문장 분리 ──────────────────────────────────────────

def test_split_sentences_korean():
    text = "첫째, 카페인은 뇌를 깨웁니다. 둘째, 향이 스트레스를 낮춥니다!"
    assert split_sentences(text) == [
        "첫째, 카페인은 뇌를 깨웁니다.",
        "둘째, 향이 스트레스를 낮춥니다!",
    ]


def test_parse_script_blocks(tmp_path: Path | None = None):
    p = Path("/tmp/_t_script.txt")
    p.write_text("# 주석\n씬1 문장. 계속.\n\n씬2 문장\n", encoding="utf-8")
    scenes = parse_script(p)
    assert len(scenes) == 2
    assert scenes[0].text == "씬1 문장. 계속."
    assert scenes[1].index == 1


# ── 프레임 양자화 ──────────────────────────────────────

def test_quantize():
    assert quantize_to_frames(3.6333, 30) == round(3.6333 * 30) / 30
    assert quantize_to_frames(0.0, 30, min_frames=15) == 0.5


# ── Whisper 단어 ↔ 대본 문장 정렬 ──────────────────────

def _words(pairs: list[tuple[str, float, float]]) -> list[dict]:
    return [{"text": t, "start": s, "end": e} for t, s, e in pairs]


def test_align_two_sentences():
    sents = ["커피 한 잔이 하루를 바꿉니다.", "지금부터 집중해 보세요."]
    words = _words(
        [
            ("커피", 0.0, 0.3), ("한", 0.3, 0.45), ("잔이", 0.45, 0.7),
            ("하루를", 0.7, 1.0), ("바꿉니다.", 1.0, 1.5),
            ("지금부터", 1.8, 2.1), ("집중해", 2.1, 2.5), ("보세요.", 2.5, 2.9),
        ]
    )
    subs = align_sentences(sents, words, start_offset=10.0, scene_dur=4.0)

    assert [s["text"] for s in subs] == sents            # 대본 텍스트 100% 보존
    assert subs[0]["start"] == 10.0                       # 씬 오프셋 적용
    assert abs(subs[0]["end"] - 11.5) < 1e-6
    assert abs(subs[1]["start"] - 11.8) < 1e-6
    # 시간 단조 증가
    for a, b in zip(subs, subs[1:]):
        assert b["start"] >= a["end"]
    # karaoke 토큰: 첫 문장 "커피 한 잔이 하루를 바꿉니다." → 5토큰
    toks = subs[0]["tokens"]
    assert [t["text"] for t in toks] == ["커피", "한", "잔이", "하루를", "바꿉니다."]
    for t1, t2 in zip(toks, toks[1:]):
        assert t2["start"] >= t1["start"]


def test_align_falls_back_to_proportional_without_words():
    sents = ["짧은 문장.", "아주 아주 길고 긴 두 번째 문장입니다."]
    subs = align_sentences(sents, [], start_offset=0.0, scene_dur=4.0)
    assert subs[0]["start"] == 0.0
    assert subs[1]["end"] <= 4.0 + 1e-6
    assert subs[1]["end"] - subs[0]["end"] > 0          # 긴 문장이 더 오래
    assert (subs[1]["end"] - subs[1]["start"]) > (subs[0]["end"] - subs[0]["start"])


def test_align_words_run_out_midway():
    sents = ["첫 문장입니다.", "둘 문장.", "셋 문장."]
    words = _words([("첫", 0.0, 0.3), ("문장입니다.", 0.3, 0.9)])
    subs = align_sentences(sents, words, start_offset=5.0, scene_dur=3.0)
    assert len(subs) == 3
    assert subs[0]["start"] == 5.0
    assert subs[1]["start"] >= subs[0]["end"]           # 꼬리는 비례 배분
    assert subs[2]["end"] <= 5.0 + 3.0 + 1e-6


def test_normalize():
    assert normalize("커피, 한 잔!") == "커피한잔"
    assert normalize("ABC 123") == "abc123"


# ── AI 대본 생성(scriptgen) ───────────────────────────

import tempfile

from pipeline import scriptgen as sg


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_build_prompt_placeholders():
    tpl = "주제: {topic}\n씬 {scene_count}개 {duration}초 {tone}\n"
    out = sg.build_prompt(tpl, topic="커피", scenes=4, duration=30, tone="경쾌")
    assert "주제: 커피" in out and "씬 4개" in out and "30초" in out and "경쾌" in out
    assert "{topic}" not in out and "씬 4개로 작성" in out  # per-scene 힌트 부착


def test_clean_script_strips_fences_and_numbering():
    raw = """```text
씬 1: 믿기 어렵겠지만 이건 사실입니다.

2. 핵심은 하나뿐입니다. 지금 보여드릴게요!
```"""
    out = sg.clean_script(raw, expect_scenes=2)
    scenes = out.split("\n\n")
    assert len(scenes) == 2
    assert scenes[0] == "믿기 어렵겠지만 이건 사실입니다."
    assert "```" not in out and "씬 1" not in out


def test_clean_script_appends_period_and_rejects_garbage():
    out = sg.clean_script("문장 하나가 있어요\n\n마침표 없는 문장")
    assert out.endswith("마침표 없는 문장.")
    try:
        sg.clean_script("   \n\n   ")
        assert False, "빈 대본은 예외여야 함"
    except sg.ScriptGenError:
        pass


def test_generate_script_mock_provider(tmp: Path | None = None):
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        prompt = _write(d / "p.txt", "역할: 작가\n주제: {topic}\n분량: {duration}초 (씬 {scene_count}개)")
        llm = _write(d / "llm.json", '{"provider": "mock"}')
        text = sg.generate_script("카페인의 과학", scenes=4, duration=30, prompt_path=prompt, llm_path=llm)
        scenes = [b for b in text.split("\n\n") if b.strip()]
        assert len(scenes) == 4
        assert "카페인의 과학" in scenes[0]
        # 파이프라인 파서와 호환되는지 확인
        parsed = parse_script(_write(d / "s.txt", text))
        assert len(parsed) == 4 and all(sc.sentences for sc in parsed)


# ── 직접 실행 지원 ─────────────────────────────────────

if __name__ == "__main__":
    fns = [(k, v) for k, v in globals().items() if k.startswith("test_")]
    failed = 0
    for name, fn in fns:
        try:
            fn()  # noqa: PLW2901
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} 통과")
    sys.exit(1 if failed else 0)

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


# ── Qwen3-TTS 백엔드 (스텁 주입, 네트워크/토치 불필요) ─

import math
import struct
import sys
import types as _pytypes
import wave as _wave

from pipeline.config import Settings as _Settings
from pipeline import narration as _nar


def _settings(tmp: Path, **kw) -> _Settings:
    base = dict(script_path=tmp / "s.txt", media_dir=tmp, work_dir=tmp / "w", out_dir=tmp / "o")
    base.update(kw)
    return _Settings(**base)


def _install_qwen_stubs():
    class FakeModel:
        @classmethod
        def from_pretrained(cls, model_id, device_map=None, dtype=None):
            self = cls()
            self.model_id = model_id
            return self

        def generate_custom_voice(self, text, language, speaker, **kw):
            sr = 24000
            n = sr // 2  # 0.5초 사인파
            return [[math.sin(2 * math.pi * 440 * i / sr) for i in range(n)]], sr

        def generate_voice_design(self, text, language, instruct):
            return self.generate_custom_voice(text, language, "design")

        def create_voice_clone_prompt(self, ref_audio, ref_text=None):
            return {"ref": ref_audio, "ref_text": ref_text}

        def generate_voice_clone(self, text, language, voice_clone_prompt):
            return self.generate_custom_voice(text, language, "clone")

    fake_qwen = _pytypes.ModuleType("qwen_tts")
    fake_qwen.Qwen3TTSModel = FakeModel

    def sf_write(path, wav, sr):
        with _wave.open(path, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(b"".join(struct.pack("<h", int(x * 30000)) for x in wav))

    fake_sf = _pytypes.ModuleType("soundfile")
    fake_sf.write = sf_write

    fake_torch = _pytypes.ModuleType("torch")
    fake_torch.bfloat16 = "bf16"
    fake_torch.float32 = "f32"
    fake_torch.cuda = _pytypes.SimpleNamespace(is_available=lambda: False)

    saved = {k: sys.modules.get(k) for k in ("qwen_tts", "soundfile", "torch")}
    sys.modules.update({"qwen_tts": fake_qwen, "soundfile": fake_sf, "torch": fake_torch})
    return saved


def _restore_modules(saved):
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def test_tts_backend_order():
    assert _nar._backend_order("auto") == ["qwen", "edge", "gtts"]
    assert _nar._backend_order("qwen,edge") == ["qwen", "edge"]
    assert _nar._backend_order("gtts") == ["gtts"]


def test_qwen_say_custom_voice_produces_mp3():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        saved = _install_qwen_stubs()
        try:
            s = _settings(d, tts_backend="qwen", qwen_device="cpu")
            out = d / "scene_00.mp3"
            _nar.synthesize_scene("테스트 문장입니다.", out, s)
            assert out.exists() and out.stat().st_size > 0
            assert out.read_bytes()[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")  # mp3 헤더
        finally:
            _restore_modules(saved)
            _nar._qwen_cache.clear()


def test_qwen_base_model_requires_ref_audio():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        saved = _install_qwen_stubs()
        try:
            s = _settings(d, tts_backend="qwen", qwen_device="cpu",
                          qwen_model="Qwen/Qwen3-TTS-12Hz-1.7B-Base")
            try:
                _nar._qwen_say("문장.", d / "x.mp3", s)
                assert False, "레퍼런스 없으면 예외여야 함"
            except RuntimeError as e:
                assert "ref" in str(e).lower() or "레퍼런스" in str(e)
        finally:
            _restore_modules(saved)
            _nar._qwen_cache.clear()


# ── 씬 팩(대본 + 미디어 프롬프트) ────────────────────────

def test_parse_scene_pack_fenced_json_and_key_variants():
    raw = (
        "```json\n"
        '{"scenes":[{"narration":"훅 문장입니다.","image_prompt":"cinematic coffee, 9:16","video_prompt":"slow dolly in"},'
        '{"text":"두 번째 씬이 끝납니다","image":"sunrise desk","motion_prompt":"pan right"}]}\n'
        "```"
    )
    pack = sg.parse_scene_pack(raw, expect_scenes=2)
    assert len(pack.scenes) == 2
    assert pack.scenes[0].narration == "훅 문장입니다."
    assert "coffee" in pack.scenes[0].image_prompt
    # 키 변형(text/image/motion_prompt) 흡수 + 종결부호 보정
    assert pack.scenes[1].narration.endswith(".")
    assert pack.scenes[1].image_prompt == "sunrise desk"
    assert pack.scenes[1].video_prompt == "pan right"


def test_parse_scene_pack_falls_back_to_prose():
    raw = "훅 문장입니다. 둘째 문장.\n\n본문 씬입니다."
    pack = sg.parse_scene_pack(raw)  # JSON 없음 → 대본만, 시각 프롬프트는 빈칸
    assert len(pack.scenes) == 2
    assert pack.scenes[0].image_prompt == "" and pack.scenes[0].video_prompt == ""
    assert len(pack.to_script().split("\n\n")) == 2


def test_generate_scene_pack_with_fake_llm():
    import json as _json

    orig_call = sg.call_llm
    fake_json = _json.dumps(
        {"scenes": [
            {"narration": "문장 하나.", "image_prompt": "img-one", "video_prompt": "vid-one"},
            {"narration": "문장 둘", "image_prompt": "img-two", "video_prompt": "vid-two"},
        ]}, ensure_ascii=False)
    sg.call_llm = lambda prompt, cfg: fake_json
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            pack = sg.generate_scene_pack(
                "테스트 주제", scenes=2, duration=20,
                prompt_path=_write(d / "p.txt", "주제: {topic}, 씬 {scene_count}개"),
                llm_path=_write(d / "l.json", '{"provider": "mock", "model": "x"}'),
            )
            j, t = sg.save_scene_pack(pack, d / "media_prompts")
            script = sg.parse_scene_pack(fake_json).to_script()
            scenes = parse_script(_write(d / "s.txt", script))
            assert len(pack.scenes) == 2
            assert pack.scenes[1].narration.endswith(".")
            assert j.exists() and t.exists()
            assert "img-one" in t.read_text(encoding="utf-8")
            assert len(scenes) == 2  # 대본은 그대로 파이프라인 입력 형식
    finally:
        sg.call_llm = orig_call


def test_generate_media_prompts_aligns_with_input_scenes():
    orig_call = sg.call_llm
    sg.call_llm = lambda prompt, cfg: (
        '[{"image_prompt": "i1", "video_prompt": "v1"},'
        ' {"image_prompt": "i2", "video_prompt": "v2"}]'
    )
    try:
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            outs = sg.generate_media_prompts(
                ["A 문장입니다.", "B 문장입니다."],
                prompt_path=_write(d / "m.txt", "대본:\n{scenes}\n(씬 {scene_count}개)"),
                llm_path=_write(d / "l.json", '{"provider": "mock", "model": "x"}'),
            )
        assert [o.narration for o in outs] == ["A 문장입니다.", "B 문장입니다."]
        assert outs[0].image_prompt == "i1" and outs[0].video_prompt == "v1"
        assert outs[1].image_prompt == "i2"
    finally:
        sg.call_llm = orig_call


# ── SQLite 설정 스토어 / 미리보기 ───────────────────────

def test_settings_store_set_get_section_delete():
    from pipeline import settings_store as ss

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "s.db"
        ss.set(db, "llm.provider", "mock")
        ss.set(db, "llm.temperature", 0.7)     # JSON 타입 보존
        ss.set(db, "studio.voice", "Sohee")
        assert ss.get(db, "llm.provider") == "mock"
        assert ss.get(db, "llm.temperature") == 0.7
        assert ss.get(db, "missing", "기본") == "기본"
        sec = ss.get_section(db, "llm")
        assert sec["provider"] == "mock" and sec["temperature"] == 0.7
        ss.delete(db, "studio.voice")
        assert ss.get(db, "studio.voice") is None
        # 시크릿 자동 생성+재사용
        a = ss.get_or_create_secret(db)
        assert ss.get_or_create_secret(db) == a and len(a) >= 32


def test_settings_store_admin_password_flow():
    from pipeline import settings_store as ss

    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "s.db"
        assert ss.admin_count(db) == 0
        ss.create_admin(db, "admin", "secret1")
        assert ss.admin_count(db) == 1
        assert ss.verify_admin(db, "admin", "secret1")
        assert not ss.verify_admin(db, "admin", "wrong")
        assert not ss.verify_admin(db, "nobody", "secret1")
        ss.change_password(db, "admin", "newpass99")
        assert ss.verify_admin(db, "admin", "newpass99")
        assert not ss.verify_admin(db, "admin", "secret1")
        try:
            ss.create_admin(db, "admin", "123")   # 6자 미만 거부
            raise AssertionError("짧은 비밀번호가 통과됨")
        except ValueError:
            pass


def test_scriptgen_llm_overrides_merge():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        cfg = _write(d / "llm.json",
                     '{"provider": "mock", "model": "a", "temperature": 0.2}')
        merged = sg._effective_llm_config(cfg, {"model": "b", "base_url": "http://x", "provider": "openai-compatible"})
        assert merged["model"] == "b" and merged["base_url"] == "http://x"
        assert merged["provider"] == "openai-compatible"
        assert merged["temperature"] == 0.2   # 오버라이드 미지정 → 기존값 유지
        cleaned = sg._effective_llm_config(cfg, {"model": "", "base_url": None})  # 빈 값은 무시
        assert cleaned["model"] == "a"


def test_preview_font_and_audio_graph_helpers():
    from pipeline import preview as pv

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        f = _write(d / "Font.ttf", "FAKE-TTF-BYTES")
        assert pv.resolve_subtitle_font(f) == Path(f)          # 명시 경로 우선
        # 경로 이스케이프(콜론/따옴표)
        esc = pv._vf_unquote_path(d / "a:b'c / f.srt")
        assert "\\:" in esc and "\\'" in esc
    # 오디오 그래프: BGM 없음 → anull, BGM+덕킹 → sidechaincompress
    class _S:  # 최소 Settings 모사
        bgm_path = None; bgm_volume = 0.2; duck_bgm = True
        bgm = None
    g, label = pv._audio_graph(_S(), 5.0, 1, None)
    assert "anull" in g and label == "a"
    class _S2:
        bgm_path = "/tmp/bgm.mp3"; bgm_volume = 0.2; duck_bgm = True
        bgm = "/tmp/bgm.mp3"
    g2, _ = pv._audio_graph(_S2(), 5.0, 1, 2)
    assert "sidechaincompress" in g2 and "volume=0.200" in g2


def test_youtube_doc_template_contract():
    """유튜브 다큐 템플릿: 치환/출력계약/시그니처 문구 유지 확인."""
    tpl_path = Path("admin/youtube_doc_prompt.txt")
    raw = tpl_path.read_text(encoding="utf-8")
    filled = sg.build_prompt(raw, topic="잠수함의 비밀", scenes=5, duration=240, tone="다큐")
    assert "{topic}" not in filled                    # 치환 완료
    assert "잠수함의 비밀" in filled
    assert "[영상 주제]" in raw
    assert "[출력 형식" in raw                        # 파서 계약 섹션 존재
    for sig in ("미치고 환장할 노릇입니다", "발상을 뒤집습니다", "경이롭지 않나요", "빈 줄"):
        assert sig in raw, f"시그니처/계약 문구 누락: {sig}"


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

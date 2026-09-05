"""AI 대본 생성기: 관리자 프롬프트 템플릿 + 주제 → 파이프라인 포맷 대본.

구성:
  * admin/script_prompt.txt — 관리자가 직접 고치는 프롬프트 ({topic} 등 치환 변수)
  * admin/llm.json         — LLM 연결 설정 (로컬은 admin/llm.local.json)
  * 백엔드: OpenAI 호환 Chat Completions (OpenAI/Ollama/LM Studio/프록시 공통)
            provider=mock 이면 네트워크 없이 시연/테스트용 대본 생성
출력은 clean_script()로 검증·정규화되어 파이프라인 파서 규격(빈 줄=씬,
문장은 . ! ? 종료)을 보장한다.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .common import log, warn
from .script_parser import split_sentences

DEFAULTS = {
    "provider": "openai-compatible",
    "model": None,
    "base_url": None,
    "api_key_env": "OPENAI_API_KEY",
    "temperature": 0.8,
    "max_tokens": 1200,
}

PLACEHOLDERS = ("topic", "scene_count", "duration", "tone", "media_lang", "scenes")


class ScriptGenError(RuntimeError):
    """대본 생성 실패(사용자 안내 가능한 오류)."""


# ── 설정 로드 ─────────────────────────────────────────

def load_llm_config(path: Path | str | None) -> dict:
    cfg = dict(DEFAULTS)
    path = Path(path) if path else None
    if path and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in data.items() if not k.startswith("_")})
        except Exception as e:
            raise ScriptGenError(f"LLM 설정 파일 파싱 실패({path}): {e}")
    # 로컬 오버라이드(git 미추적) 우선
    if path:
        local = path.with_name(path.stem + ".local.json")
        if local.exists():
            try:
                data = json.loads(local.read_text(encoding="utf-8"))
                cfg.update({k: v for k, v in data.items() if not k.startswith("_")})
                log(f"  로컬 LLM 설정 적용: {local}")
            except Exception as e:
                warn(f"{local} 파싱 실패(무시): {e}")
    # 환경 변수 평활
    cfg["model"] = cfg.get("model") or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    cfg["base_url"] = cfg.get("base_url") or os.environ.get("OPENAI_BASE_URL")
    if cfg.get("api_key"):
        raise ScriptGenError("LLM 설정 파일에 api_key를 직접 쓰지 마세요. api_key_env(환경변수 이름)만 사용하세요.")
    return cfg


def load_prompt_template(path: Path | str) -> str:
    p = Path(path)
    if not p.exists():
        raise ScriptGenError(f"프롬프트 템플릿이 없습니다: {p} (관리자가 작성해 두어야 합니다)")
    text = p.read_text(encoding="utf-8").strip()
    # 파일 맨 위의 '# ...' 주석 블록은 프롬프트에서 제외
    text = re.sub(r"\A(?:\s*#[^\n]*\n)+", "", text)
    return text


# ── 프롬프트 조립 ─────────────────────────────────────

def build_prompt(template: str, *, topic: str, scenes: int, duration: int, tone: str,
                 media_lang: str = "English", scenes_text: str = "") -> str:
    values = {
        "topic": topic, "scene_count": scenes, "duration": duration,
        "tone": tone, "media_lang": media_lang, "scenes": scenes_text or topic,
    }
    out = template
    for key in PLACEHOLDERS:
        out = out.replace("{" + key + "}", str(values[key]))
    per = round(duration / max(1, scenes), 1)
    out += f"\n(참고: 씬당 목표 약 {per}초. 반드시 씬 {scenes}개로 작성.)"
    return out


# ── LLM 호출 ──────────────────────────────────────────

def call_llm(prompt: str, cfg: dict) -> str:
    if cfg.get("provider") == "mock":
        return _mock_answer(prompt)

    key_name = cfg.get("api_key_env") or "OPENAI_API_KEY"
    api_key = os.environ.get(key_name)
    if not api_key:
        raise ScriptGenError(
            f"환경변수 {key_name} 가 설정되지 않았습니다.\n"
            f"  export {key_name}=<키>\n"
            "또는 admin/llm.json 의 provider 를 \"mock\" 으로 바꿔 오프라인 시연이 가능합니다."
        )
    try:
        from openai import OpenAI  # 지연 import
    except ImportError as e:
        raise ScriptGenError(f"openai 패키지가 없습니다: pip install openai ({e})")

    client = OpenAI(api_key=api_key, base_url=cfg.get("base_url") or None, timeout=180)
    try:
        resp = client.chat.completions.create(
            model=cfg["model"],
            messages=[{"role": "user", "content": prompt}],
            temperature=float(cfg.get("temperature", 0.8)),
            max_tokens=int(cfg.get("max_tokens", 1200)),
        )
    except Exception as e:  # noqa: BLE001
        raise ScriptGenError(f"LLM 호출 실패(model={cfg['model']}): {e}")
    text = resp.choices[0].message.content if resp.choices else ""
    if not text or not text.strip():
        raise ScriptGenError("LLM이 빈 응답을 반환했습니다.")
    return text


def _mock_answer(prompt: str) -> str:
    """오프라인 시연/테스트용: 프롬프트 의도를 감지해 형식만 맞춰 응답.

    - image_prompt 키 계약 + 번호 목록 대본 → 미디어 프롬프트 전용(JSON 배열)
    - image_prompt 키 계약 → 씬 팩(JSON {"scenes": [...]})
    - 그 외 → 대본 텍스트(빈 줄 구분)
    """
    m = re.search(r"주제:\s*(.+)", prompt)
    topic = (m.group(1).strip() if m else "이 주제")[:30]
    sc = re.search(r"씬\s*(\d+)\s*개", prompt)
    wants_media = "image_prompt" in prompt or "video_prompt" in prompt

    # 미디어 프롬프트 전용 호출: 번호가 매겨진 대본 목록을 그대로 미러
    numbered = [n.strip() for n in re.findall(r"^\d+\.\s*(.+)$", prompt, flags=re.M)]
    if wants_media and numbered:
        items = [
            {
                "narration": n,
                "image_prompt": f"Vertical 9:16 still, {topic}, scene {i + 1}, warm cinematic lighting, detailed composition",
                "video_prompt": f"Vertical 9:16 clip, {topic}, scene {i + 1}, gentle subject motion, slow dolly-in",
            }
            for i, n in enumerate(numbered)
        ]
        return json.dumps(items, ensure_ascii=False)

    scenes = int(sc.group(1)) if sc else 4
    hook = f"잠깐, {topic}에 대해 얼마나 알고 계신가요? 지금부터 핵심만 콕 짚어 드릴게요."
    outro = f"오늘부터 {topic}, 아주 작게 시작해 보세요. 이 영상이 도움이 됐다면 저장해 두세요."
    middles = [
        f"먼저, {topic}의 핵심은 생각보다 단순합니다. 작은 차이가 큰 결과를 만듭니다.",
        f"두 번째로, 전문가들은 늘 원리부터 봅니다. 이유를 알면 응용은 저절로 됩니다.",
        f"가장 많이 하는 실수는 처음부터 완벽하려는 겁니다. 대신 오늘 한 가지만 바꿔 보세요.",
    ]
    body = ([hook] + middles[: max(0, scenes - 2)] + [outro])[:scenes]

    if wants_media:
        items = [
            {
                "narration": n,
                "image_prompt": f"Vertical 9:16 still, {topic} — scene {i + 1} establishing shot, cinematic color grade",
                "video_prompt": f"Vertical 9:16 clip, {topic} — scene {i + 1}, subtle camera push-in, natural motion",
            }
            for i, n in enumerate(body)
        ]
        return json.dumps({"scenes": items}, ensure_ascii=False)
    return "\n\n".join(body)


# ── 출력 정제·검증 ────────────────────────────────────

_FENCE_RE = re.compile(r"^```[a-zA-Z가-힣]*\s*|\s*```$")
_NUM_PREFIX_RE = re.compile(
    r"^\s*(?:\d+\s*[.)\]|]|씬\s*\d+\s*[:：.\]-]?|scene\s*\d+\s*[:：.\]-]?)\s*", re.IGNORECASE
)


def clean_script(text: str, expect_scenes: int | None = None) -> str:
    """LLM 출력을 파이프라인 규격으로 정규화 + 검증."""
    t = text.strip()
    if t.startswith("```"):
        t = _FENCE_RE.sub("", t).strip()
    lines = [_NUM_PREFIX_RE.sub("", ln).rstrip() for ln in t.splitlines()]
    blocks = re.split(r"\n\s*\n", "\n".join(lines).strip())
    scenes = [re.sub(r"\s*\n\s*", " ", b).strip() for b in blocks if b.strip()]
    scenes = [b for b in scenes if split_sentences(b)]  # 자막 가능 문장이 있는 블록만

    if not scenes:
        raise ScriptGenError(
            "생성 결과에서 대본 씬을 찾지 못했습니다. 프롬프트의 [출력 형식] 규칙을 확인하세요."
        )
    if expect_scenes and len(scenes) != expect_scenes:
        warn(f"씬 개수 불일치(요청 {expect_scenes}, 생성 {len(scenes)}). 생성값을 그대로 사용합니다.")
    for i, b in enumerate(scenes):
        if not re.search(r"[.!?…。]\s*$", b):
            scenes[i] = b.rstrip() + "."  # 문장 종결 보정
    return "\n\n".join(scenes)


# ── 통합 엔트리 ───────────────────────────────────────

def generate_script(
    topic: str,
    *,
    scenes: int = 4,
    duration: int = 30,
    tone: str = "정보 전달·실용 꿀팁",
    prompt_path: Path | str,
    llm_path: Path | str | None = None,
) -> str:
    if not topic.strip():
        raise ScriptGenError("주제가 비어 있습니다.")
    cfg = load_llm_config(llm_path)
    template = load_prompt_template(prompt_path)
    prompt = build_prompt(template, topic=topic, scenes=scenes, duration=duration, tone=tone)
    log(f"  LLM 호출: provider={cfg.get('provider')} model={cfg.get('model')} (주제: {topic})")
    raw = call_llm(prompt, cfg)
    script = clean_script(raw, expect_scenes=scenes)
    n = len(re.split(r"\n\s*\n", script))
    log(f"  대본 생성 완료: {n}씬 / {len(script)}자")
    return script


def save_script(script: str, path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(script + "\n", encoding="utf-8")
    log(f"  대본 저장: {p}")
    return p


# ══════════════════════════════════════════════════════════════════
#  씬 팩: 대본 + 이미지/동영상 생성 프롬프트
# ══════════════════════════════════════════════════════════════════

from dataclasses import dataclass  # noqa: E402  (하단 확장 섹션 가독성)


@dataclass
class ScenePrompts:
    index: int
    narration: str
    image_prompt: str = ""
    video_prompt: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "narration": self.narration,
            "image_prompt": self.image_prompt,
            "video_prompt": self.video_prompt,
        }


@dataclass
class ScenePack:
    """대본(나레이션) + 씬별 시각 생성 프롬프트 묶음."""

    scenes: list[ScenePrompts]

    def to_script(self) -> str:
        return "\n\n".join(sc.narration for sc in self.scenes)

    def to_json(self) -> dict:
        return {"scenes": [sc.to_dict() for sc in self.scenes]}

    def to_prompts_text(self) -> str:
        parts = ["# AI 미디어 생성 프롬프트 (씬별 복사 → 영상/이미지 생성 툴에 붙여넣기)\n"]
        for sc in self.scenes:
            parts.append(
                f"════════════════ 씬 {sc.index + 1} ════════════════\n"
                f"대본: {sc.narration}\n\n"
                f"[이미지 프롬프트]\n{sc.image_prompt or '(없음)'}\n\n"
                f"[동영상 프롬프트]\n{sc.video_prompt or '(없음)'}\n"
            )
        return "\n".join(parts)


# LLM이 자주 바꿔 쓰는 키 이름들을 흡수한다
_PACK_KEY_VARIANTS = {
    "narration": ("narration", "narration_text", "script", "text", "voiceover",
                  "대본", "나레이션", "날arr"),
    "image_prompt": ("image_prompt", "image", "img_prompt", "imageprompt",
                     "image_generation_prompt", "이미지 프롬프트", "이미지"),
    "video_prompt": ("video_prompt", "video", "motion_prompt", "clip_prompt",
                     "video_motion_prompt", "동영상 프롬프트", "영상 프롬프트"),
}


def _normalize_key(key: str) -> str | None:
    lk = key.strip().lower()
    for canon, variants in _PACK_KEY_VARIANTS.items():
        if lk in variants or key.strip() in variants:
            return canon
    return None


_JSON_BLOCK_RE = re.compile(r"(\[[\s\S]*\]|\{[\s\S]*\})")


def _first_json(raw: str):
    """출력에서 첫 JSON 묶음을 찾아 파싱. 실패 시 None."""
    t = raw.strip()
    if t.startswith("```"):
        t = _FENCE_RE.sub("", t).strip()
    try:
        return json.loads(t)
    except Exception:  # noqa: BLE001
        pass
    m = _JSON_BLOCK_RE.search(t)
    while m:
        try:
            return json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            # 배열 안쪽 중괄호만 다시 시도
            t = m.group(1)
            inner = re.search(r"\{[\s\S]*\}", t)
            m = inner if inner and inner.group(0) != t else None
    return None


def _pick(d: dict, canon: str) -> str:
    for k, v in d.items():
        if _normalize_key(k) == canon:
            return str(v).strip() if v is not None else ""
    return ""


def parse_scene_pack(raw: str, expect_scenes: int | None = None) -> ScenePack:
    """LLM 출력(JSON 우선)을 ScenePack으로. JSON이 없으면 대본만으로 평활."""
    data = _first_json(raw)

    if data is None:
        warn("LLM 응답에서 JSON을 찾지 못했습니다. 대본만 생성하고 시각 프롬프트는 비웁니다.")
        script = clean_script(raw, expect_scenes=expect_scenes)
        blocks = [b.strip() for b in re.split(r"\n\s*\n", script) if b.strip()]
        return ScenePack([ScenePrompts(index=i, narration=b) for i, b in enumerate(blocks)])

    if isinstance(data, dict):
        arr = data.get("scenes") or data.get("items") or data.get("data") or []
    elif isinstance(data, list):
        arr = data
    else:
        arr = []

    scenes: list[ScenePrompts] = []
    for item in arr:
        if isinstance(item, str) and item.strip():
            scenes.append(ScenePrompts(index=len(scenes), narration=item.strip()))
        elif isinstance(item, dict):
            narr = _pick(item, "narration")
            img = _pick(item, "image_prompt")
            vid = _pick(item, "video_prompt")
            if not (narr or img or vid):
                continue
            scenes.append(
                ScenePrompts(index=len(scenes), narration=narr,
                             image_prompt=img, video_prompt=vid)
            )

    if not scenes:
        warn("JSON을 파싱했지만 씬을 찾지 못했습니다. 대본 텍스트로 평활합니다.")
        script = clean_script(raw, expect_scenes=expect_scenes)
        blocks = [b.strip() for b in re.split(r"\n\s*\n", script) if b.strip()]
        return ScenePack([ScenePrompts(index=i, narration=b) for i, b in enumerate(blocks)])

    # 문장 종결 보정 (자막 규칙과 동일, 빈 나레이션 제외)
    for sc in scenes:
        if sc.narration and not re.search(r"[.!?…。]\s*$", sc.narration):
            sc.narration = sc.narration.rstrip() + "."
    if expect_scenes and len(scenes) != expect_scenes:
        warn(f"씬 개수 불일치(요청 {expect_scenes}, 생성 {len(scenes)}). 생성값 사용.")
    no_media = sum(1 for sc in scenes if not sc.image_prompt and not sc.video_prompt)
    if no_media:
        warn(f"시각 프롬프트가 비어 있는 씬 {no_media}개 — 템플릿의 JSON 출력 계약을 확인하세요.")
    return ScenePack(scenes)


def generate_scene_pack(
    topic: str,
    *,
    scenes: int = 4,
    duration: int = 30,
    tone: str = "정보 전달·실용 꿀팁",
    media_lang: str = "English",
    prompt_path: Path | str,
    llm_path: Path | str | None = None,
) -> ScenePack:
    """주제 → (대본 + 이미지/동영상 프롬프트) 씬 팩."""
    if not topic.strip():
        raise ScriptGenError("주제가 비어 있습니다.")
    cfg = load_llm_config(llm_path)
    template = load_prompt_template(prompt_path)
    prompt = build_prompt(
        template, topic=topic, scenes=scenes, duration=duration, tone=tone,
        media_lang=media_lang,
    )
    log(f"  LLM 씬 팩 생성: provider={cfg.get('provider')} model={cfg.get('model')} (주제: {topic})")
    raw = call_llm(prompt, cfg)
    pack = parse_scene_pack(raw, expect_scenes=scenes)
    log(f"  씬 팩 완료: {len(pack.scenes)}씬, 시각 프롬프트 {sum(bool(s.image_prompt) for s in pack.scenes)}개 이미지 / {sum(bool(s.video_prompt) for s in pack.scenes)}개 영상")
    return pack


def generate_media_prompts(
    scene_texts: list[str],
    *,
    media_lang: str = "English",
    prompt_path: Path | str,
    llm_path: Path | str | None = None,
) -> list[ScenePrompts]:
    """완성된 대본(직접 입력/외부 AI) → 씬별 이미지/동영상 프롬프트."""
    scene_texts = [t.strip() for t in scene_texts if t.strip()]
    if not scene_texts:
        raise ScriptGenError("대본이 비어 있습니다.")
    cfg = load_llm_config(llm_path)
    template = load_prompt_template(prompt_path)
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(scene_texts))
    prompt = build_prompt(
        template, topic=scene_texts[0], scenes=len(scene_texts), duration=0,
        tone="", media_lang=media_lang, scenes_text=numbered,
    )
    log(f"  LLM 미디어 프롬프트 생성: {len(scene_texts)}씬 (provider={cfg.get('provider')})")
    raw = call_llm(prompt, cfg)
    pack = parse_scene_pack(raw)
    # 나레이션은 입력 대본을 그대로 유지하고, 개수는 입력 기준으로 맞춤
    out: list[ScenePrompts] = []
    for i, text in enumerate(scene_texts):
        src = pack.scenes[i] if i < len(pack.scenes) else ScenePrompts(index=i, narration=text)
        out.append(ScenePrompts(index=i, narration=text,
                                image_prompt=src.image_prompt, video_prompt=src.video_prompt))
    return out


def save_scene_pack(pack: ScenePack, out_prefix: Path | str) -> tuple[Path, Path]:
    """media_prompts.json / media_prompts.txt 저장 경로 (접미사 없이 prefix 전달)."""
    p = Path(out_prefix)
    p.parent.mkdir(parents=True, exist_ok=True)
    j = p.with_suffix(".json")
    t = p.with_suffix(".txt")
    j.write_text(json.dumps(pack.to_json(), ensure_ascii=False, indent=2), encoding="utf-8")
    t.write_text(pack.to_prompts_text(), encoding="utf-8")
    log(f"  미디어 프롬프트 저장: {j.name}, {t.name}")
    return j, t

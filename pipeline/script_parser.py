"""대본(script.txt) 파서.

규칙:
  * 빈 줄(2개 이상의 개행)로 씬(scene)을 구분한다. 씬 1개 = 미디어 1개와 매칭.
  * '#'으로 시작하는 줄은 주석.
  * 씬 안의 문장은 자막 한 줄 단위가 된다.
    - 마침표/물음표/느낌표/말줄임표 뒤 공백, 또는 줄바꿈으로 문장을 나눈다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# 한국어 문장부호 뒤의 공백/줄바꿈을 문장 경계로 인식
_SENT_SPLIT = re.compile(r"(?<=[.!?…。])\s+|\n+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT.split(text.strip()) if s.strip()]


@dataclass
class Scene:
    index: int
    text: str
    sentences: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"index": self.index, "text": self.text, "sentences": self.sentences}


def parse_script(path: Path) -> list[Scene]:
    raw = Path(path).read_text(encoding="utf-8")
    # 주석 제거
    lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("#")]
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        return []

    blocks = re.split(r"\n\s*\n", cleaned)
    scenes: list[Scene] = []
    for i, block in enumerate(blocks):
        text = re.sub(r"\s*\n\s*", " ", block.strip())  # 씬 난독화 방지: 한 줄로
        if not text:
            continue
        scenes.append(Scene(index=len(scenes), text=text, sentences=split_sentences(text)))
    return scenes

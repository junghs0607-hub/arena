"""Abstract LLM / STT / TTS providers with mock implementations."""
from __future__ import annotations

import hashlib
import json
import os
from abc import ABC, abstractmethod
from typing import Any

import requests
from flask import current_app


def cache_key(*parts: str) -> str:
    h = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return h


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt: str, system: str = "") -> str:
        ...


class MockLLMProvider(LLMProvider):
    def complete(self, prompt: str, system: str = "") -> str:
        if "제목" in prompt or "title" in prompt.lower():
            return json.dumps(
                [
                    {"title": "원본을 새롭게 해석한 핵심 이야기", "score": 86},
                    {"title": "당신이 몰랐던 한 가지 사실", "score": 81},
                    {"title": "60초 만에 정리하는 핵심 포인트", "score": 78},
                ],
                ensure_ascii=False,
            )
        if "분석" in prompt or "analysis" in prompt.lower():
            return json.dumps(
                {
                    "hook": "첫 3초에 질문을 던져 관심을 끈다",
                    "core_message": "원본의 핵심 사실만 추출해 새 해설을 구성",
                    "emotion": "호기심",
                    "structure": ["hook", "problem", "insight", "twist", "cta"],
                    "redundant": [],
                    "scenes": 5,
                },
                ensure_ascii=False,
            )
        return (
            "0~3초: 이 장면, 왜 사람들이 멈출까요?\n"
            "3~10초: 대부분은 겉모습만 보고 지나칩니다.\n"
            "10~35초: 핵심은 구조와 맥락입니다. 원본에서 확인된 사실만 새 이야기로 재구성합니다.\n"
            "35~50초: 그런데 진짜 반전은 여기에 있습니다.\n"
            "50~60초: 더 알고 싶다면 다음 영상에서 이어갑니다. 구독과 좋아요 부탁드려요."
        )


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model

    def complete(self, prompt: str, system: str = "") -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "You are a Korean video script writer."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
        }
        r = requests.post(f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


def get_llm() -> LLMProvider:
    name = current_app.config.get("LLM_PROVIDER", "mock")
    if name in ("openai", "ollama", "lmstudio", "gemini", "claude") and current_app.config.get("LLM_API_KEY"):
        return OpenAICompatibleProvider(
            current_app.config.get("LLM_BASE_URL") or "https://api.openai.com/v1",
            current_app.config.get("LLM_API_KEY") or "",
            current_app.config.get("LLM_MODEL") or "gpt-4o-mini",
        )
    if name in ("ollama", "lmstudio"):
        return OpenAICompatibleProvider(
            current_app.config.get("LLM_BASE_URL") or "http://localhost:11434/v1",
            current_app.config.get("LLM_API_KEY") or "ollama",
            current_app.config.get("LLM_MODEL") or "llama3",
        )
    return MockLLMProvider()


class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, language: str = "ko") -> str:
        ...


class MockSTTProvider(STTProvider):
    def transcribe(self, audio_path: str, language: str = "ko") -> str:
        return (
            "이것은 개발용 모의 전사입니다. "
            "실제 STT 키가 설정되면 음성에서 텍스트를 추출합니다. "
            "핵심 메시지를 바탕으로 새로운 한국어 대본을 작성합니다."
        )


def get_stt() -> STTProvider:
    return MockSTTProvider()


class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: str, language: str = "ko", style: str = "friendly") -> str:
        ...


class MockTTSProvider(TTSProvider):
    def synthesize(self, text: str, output_path: str, language: str = "ko", style: str = "friendly") -> str:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # WAV header + silence-ish payload so players don't always fail
        with open(output_path, "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt ")
            f.write(b"\x10\x00\x00\x00\x01\x00\x01\x00")
            f.write(b"\x44\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00")
            f.write(text.encode("utf-8")[:200])
        return output_path


def get_tts() -> TTSProvider:
    return MockTTSProvider()


def parse_jsonish(text: str) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return text

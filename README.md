# Arena Studio — AI 영상 재제작 · YouTube 자동화

권리가 확인된 소스 영상을 분석하고, **새로운 대본·내레이션·자막·편집·썸네일·메타데이터**로 재구성한 뒤 YouTube에 예약 게시하는 Flask 플랫폼입니다.

## 저작권

- DRM/로그인/다운로드 제한 우회, 워터마크 제거, Content ID 회피 기능은 **없습니다**.
- 소스 등록 시 권리 확인 체크가 없으면 자동 제작이 차단됩니다.
- URL은 출처 기록용이며, 보호된 원격 영상은 다운로드하지 않습니다.

## 빠른 시작 (로컬 SQLite)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
export FLASK_APP=wsgi:app
python wsgi.py
```

기본 로그인: `admin@example.com` / `admin1234`

API 키가 없으면 Mock LLM/STT/TTS/YouTube로 전체 파이프라인이 동작합니다.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

서비스: Flask, PostgreSQL, Redis, Celery worker, Celery beat, Nginx.

## 파이프라인

`소스 등록 → 권리 확인 → 분석 → STT → 대본 → TTS → 자막 → FFmpeg 렌더 → 썸네일 → 메타 → 검수 → YouTube(실API 또는 Mock)`

각 단계는 프로젝트 화면에서 개별 실행하거나 `전체 파이프라인`으로 한 번에 실행합니다. Celery가 있으면 워커에서 렌더링할 수 있습니다.

## 환경 변수

`.env.example` 참고. `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`로 Ollama·LM Studio·OpenAI 호환 API를 연결합니다.

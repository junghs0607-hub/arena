# ClipForge AI

Next.js + TypeScript 기반의 합법적 영상 자동화 플랫폼 기반입니다.

## 구현 범위
- PostgreSQL/Drizzle 스키마: users, sources, projects, scenes, transcripts, scripts, TTS, subtitles, renders, thumbnails, YouTube, jobs, schedules, providers, settings
- Mock AI Provider 교체 인터페이스
- 영상 소스/프로젝트 CRUD API
- pipeline job payload 및 재시도 가능한 상태 모델
- FFmpeg 세로 영상 렌더링/오디오 추출 모듈
- 저작권 확인 없는 소스 생성 차단
- YouTube OAuth 토큰을 DB에 평문 저장하지 말고 운영 환경에서는 암호화 저장소 사용

## 시작
1. PostgreSQL 생성 후 `.env.example`을 `.env.local`로 복사하고 DATABASE_URL 설정
2. `npm run db:push`
3. `npm run dev`

API: `GET/POST /api/sources`, `GET/POST /api/projects`

MockAIProvider는 `lib/ai/provider.ts`의 `getAIProvider`를 OpenAI/Gemini/Ollama 구현체로 교체하는 확장 지점입니다. URL 다운로드는 권리 확인 및 제공자가 허용한 소스만 애플리케이션 레이어에서 허용해야 합니다.

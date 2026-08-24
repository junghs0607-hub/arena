# ClipForge AI

인증 세션 기반 영상 자동화 플랫폼 기반입니다.

## 실행
```bash
cp .env.example .env.local
npm install
docker compose up -d
npm run db:push
npm run dev
# 별도 터미널
npm run worker
```

## 인증 API
`POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `GET /auth`.

소스, 프로젝트, Job, Queue, 통계 API는 세션이 필요합니다. 프로젝트/소스 생성 및 조회는 사용자별로 분리됩니다.

## 미디어/Pipeline API
`/api/uploads`, `/api/metadata`, `/api/stt`, `/api/tts`, `/api/render`, `/api/thumbnail`, `/api/subtitles`, `/api/youtube/upload`, `/api/pipeline`, `/api/queue`, `/api/jobs/run`.

외부 URL은 반드시 사용 권한을 보유한 소스만 처리해야 합니다. 운영에서는 모든 미디어 API에 세션 및 리소스 소유권 검사를 적용하고 S3/MinIO, 이메일 Provider, OAuth state 검증, Redis rate limit을 사용해야 합니다.

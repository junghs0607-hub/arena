# ClipForge AI

인증·소유권 기반 영상 자동화 플랫폼 기반입니다.

## 실행
```bash
cp .env.example .env.local
npm install
docker compose up -d
npm run db:push
npm run dev
npm run worker
```

## 보안 적용
세션이 필요한 API와 프로젝트/소스 소유권 검사를 적용합니다. Source, Project, Job, Queue, Schedule, Pipeline은 사용자별로 격리됩니다. 미디어 API는 `projectId`/`sourceId`를 함께 보내면 소유권 확인을 수행합니다.

## 주요 API
`/api/auth/*`, `/api/sources`, `/api/projects`, `/api/uploads`, `/api/metadata`, `/api/stt`, `/api/tts`, `/api/render`, `/api/thumbnail`, `/api/subtitles`, `/api/pipeline`, `/api/queue`, `/api/jobs`, `/api/schedules`, `/api/youtube/*`, `/api/statistics`.

외부 URL은 반드시 사용 권한을 보유한 소스만 처리해야 합니다. 운영에서는 S3/MinIO, 이메일 Provider, OAuth state 검증, Redis rate limit을 사용해야 합니다.

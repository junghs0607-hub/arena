# ClipForge AI

## Auth
`POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `GET /auth`.

Source and project APIs now require a session and scope reads/writes to the authenticated user. Jobs and statistics also require a session. Admin endpoints use `requireAdmin()`.

## 실행
```bash
cp .env.example .env.local
npm install
docker compose up -d
npm run db:push
npm run dev
npm run worker
```

## API
`/api/uploads`, `/api/metadata`, `/api/stt`, `/api/tts`, `/api/render`, `/api/thumbnail`, `/api/subtitles`, `/api/youtube/upload` provide media operations. `/api/pipeline` and `/api/queue` run AI pipelines; `/api/queue/{id}` tracks/cancels jobs. `/api/schedules` manages schedules; `/api/scheduler/tick` dispatches due schedules. `/api/statistics` returns stored totals.

Production must use S3/MinIO, authentication on every media endpoint, encrypted OAuth tokens, an email provider, and a distributed rate limiter. External URLs must only be processed with verified reuse rights.

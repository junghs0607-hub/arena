# ClipForge AI

인증·소유권 기반 영상 자동화 플랫폼.

## 실행
```bash
cp .env.example .env.local
npm install
docker compose up -d
npm run db:push
npm run dev
npm run worker
```

## Auth API
- `POST /api/auth/register`, `/login`, `/logout`, `GET /me`
- `POST /api/auth/reset/request`, `POST /api/auth/reset/confirm`
- `POST /api/auth/verification/resend`, `GET /api/auth/verify?token=...`
- `GET /api/auth/google`, `GET /api/auth/google/callback`

Source/Project/Job/Queue/Schedule/Pipeline/Media/YouTube API는 세션과 리소스 소유권을 검사합니다. 외부 URL은 사용 권한을 보유한 소스만 처리합니다. 운영에서는 이메일 Provider, Google ID token 검증, S3/MinIO, Redis rate limit을 설정하세요.

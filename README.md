# ClipForge AI

## 실행
```bash
cp .env.example .env.local
npm install
docker compose up -d
npm run db:push
npm run dev
npm run worker
```

## 인증/YouTube
`/auth` 로그인 UI. Auth API는 register/login/logout/me, password reset, email verify, Google OAuth를 제공합니다.

- `GET /api/youtube/channels`: 내 채널 목록
- `DELETE /api/youtube/channels/{id}`: 내 채널 연결 해제
- `POST /api/youtube/channels/{id}/refresh`: OAuth token 갱신
- `POST /api/youtube/upload`: 소유 channelId/projectId로 업로드
- `POST /api/statistics/sync`: 내 업로드의 YouTube 통계 동기화
- `GET /api/statistics`: 내 통계 합계

모든 Source/Project/Job/Queue/Schedule/Pipeline/Media API는 세션과 소유권을 확인합니다. 외부 URL은 재사용 권리가 확인된 소스만 처리합니다.

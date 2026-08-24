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

소스, 프로젝트, Job, Queue, 예약, 통계 및 미디어 API는 로그인 세션이 필요합니다. Source/Project/Schedule/Queue는 사용자 소유권을 검증합니다. 관리 API는 `requireAdmin()`을 사용합니다. 모든 외부 URL은 합법적 재사용 권한이 확인된 경우에만 처리해야 합니다.

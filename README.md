# ClipForge AI

## 인증
- `/auth`: 로그인/회원가입/Google OAuth
- `/auth/reset`: 비밀번호 재설정
- `/auth/verify?token=...`: 이메일 인증
- `POST /api/auth/password`: 현재 비밀번호 확인 후 변경, 기존 세션 폐기
- `POST /api/auth/logout-all`: 모든 기기 세션 폐기

회원가입 직후에는 이메일 인증 전 세션을 만들지 않습니다. 모든 보호 API는 HttpOnly 세션과 사용자 소유권을 확인합니다.

## 실행
```bash
cp .env.example .env.local
npm install
docker compose up -d
npm run db:push
npm run dev
npm run worker
```

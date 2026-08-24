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

## Auth UI
- `/auth`: 로그인/회원가입/Google 로그인/비밀번호 찾기
- `/auth/reset`: 비밀번호 재설정
- `/auth/verify?token=...`: 이메일 인증

Auth API는 register/login/logout/me, password reset request/confirm, email verification/resend, Google OAuth를 제공합니다. 운영에서는 이메일 Provider와 Google OAuth Client를 설정하세요.

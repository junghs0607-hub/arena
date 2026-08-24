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

## 영상 소스/분석
- `GET/POST /api/sources`: 사용자별 소스 목록/등록
- `GET/PATCH/DELETE /api/sources/{id}`: 소스 상세/수정/삭제
- `POST /api/sources/{id}/analyze`: 업로드된 소스 FFprobe 분석 및 DB 저장
- `POST /api/uploads`: 사용자별 로컬 업로드
- `POST /api/metadata`: 파일 즉시 FFprobe

모든 소스 API는 세션과 소유권을 검사합니다. 분석 API는 `fileKey`가 로컬 storage에 존재하는 업로드 소스에만 실행됩니다. 외부 URL은 재사용 권리가 확인된 경우에만 처리해야 합니다.

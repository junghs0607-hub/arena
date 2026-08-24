# ClipForge AI

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

## API
- `POST /api/uploads`: multipart 영상 로컬 저장
- `POST /api/metadata`: FFprobe 메타데이터
- `POST /api/stt`: Whisper CLI STT
- `POST /api/tts`: OpenAI TTS
- `POST /api/render`: Shorts/Long-form FFmpeg 렌더
- `POST /api/thumbnail`: 1280x720 JPEG 프레임
- `POST /api/subtitles`: WebVTT
- `POST /api/youtube/upload`: YouTube resumable upload
- `POST /api/pipeline`: 동기 Pipeline
- `POST /api/queue`: BullMQ 비동기 Pipeline 등록
- `GET /api/queue/{id}`: Queue 상태/진행률
- `DELETE /api/queue/{id}`: Queue 취소/삭제
- `POST /api/scheduler/tick`: 만료 예약을 Queue용 Job으로 생성
- `GET /api/statistics`: 저장된 통계 합계

외부 URL은 반드시 사용 권한을 보유한 소스만 처리해야 합니다. 운영 배포 시 local storage를 S3/MinIO로 교체하고 모든 API에 사용자 인증, 권한 검사, rate limit을 추가해야 합니다.

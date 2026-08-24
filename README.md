# ClipForge AI

## 실행
```bash
cp .env.example .env.local
npm install
docker compose up -d
npm run db:push
npm run dev
```

## 미디어 API
- `POST /api/uploads`: multipart 영상 로컬 저장
- `POST /api/metadata`: multipart 영상 FFprobe 메타데이터
- `POST /api/stt`: Whisper CLI STT, `file`, `language`
- `POST /api/tts`: OpenAI TTS (`text`, `voice`)
- `POST /api/render`: multipart 영상, `format=shorts|longform`; Shorts는 720x1280 FFmpeg 변환
- `POST /api/subtitles`: JSON segments를 WebVTT로 반환

## 자동화
- `POST /api/pipeline`: AI 분석/대본/메타데이터 Pipeline
- `POST /api/jobs/run`: DB에 생성된 Job 실행
- `GET /api/jobs`: Job 조회

외부 URL은 반드시 사용 권한을 보유한 소스만 처리해야 합니다. 운영 배포 시 `/tmp` 및 local storage를 S3/MinIO로 교체하고, 사용자 인증·권한 검사를 모든 API에 추가해야 합니다.

# 🎬 반자동 쇼츠 조립 시스템 (Semi-Auto Shorts Assembler)

**이미지/비디오는 원하는 AI 도구에서 직접 생성해 넣고, 대본(txt)만 입력하면**
나레이션 생성 → 자막 타이밍 추출 → Remotion 그래픽 합성 → 최종 비디오 조립까지
자동으로 처리하는 **반자동 쇼츠(Shorts/Reels/TikTok) 조립 시스템**입니다.

```
┌─────────────┐   ┌──────────────────────────┐   ┌─────────────┐
│ 사용자 준비  │   │  이 파이프라인 (자동)      │   │   결과물     │
│ (이미지/영상) │──▶│                            │──▶│ final.mp4   │
│ + script.txt │   │ ① TTS 나레이션 (edge-tts) │   │ 1080x1920   │
└─────────────┘   │ ② 자막 타이밍 (Whisper)    │   │ 30fps 9:16  │
                  │ ③ Remotion 그래픽 오버레이  │   │ + 자막/BGM  │
                  │ ④ FFmpeg 조립·덕킹·먹스     │   │ + srt       │
                  └──────────────────────────┘   └─────────────┘
```

---

## 1. 준비물

| 항목 | 버전 | 설치 |
|---|---|---|
| Python | 3.10+ | `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` |
| Node.js | 18+ | `npm install` |
| FFmpeg | 5+ | Ubuntu `sudo apt install ffmpeg` / macOS `brew install ffmpeg` |
| (선택) GPU | CUDA | Whisper 대형 모델 가속. 없어도 CPU로 동작 |

> `ffprobe`가 없어도 `ffmpeg`만으로 동작하며, `pip install imageio-ffmpeg`의 바이너리도 자동 인식합니다.

---

## 2. 30초 만에 첫 쇼츠 만들기

**① 씬별 이미지/비디오를 원하는 AI 도구에서 생성·다운로드한 뒤 `assets/media/`에 넣기**

파일명 **앞의 번호 = 씬 순서**입니다 (자연 정렬, `01_`, `02_` … 권장).

```
assets/media/
├── 01_hook.mp4      ← 씬 1 (비디오: 자동 cover 크롭, 짧으면 반복)
├── 02_point01.jpg   ← 씬 2 (이미지: Ken Burns 줌인 자동 적용)
├── 03_point02.png
└── 04_outro.mp4
```

**② 대본 작성 — `assets/script.txt`**

빈 줄(엔터 2번)로 씬을 구분합니다. **씬 1개 = 미디어 1개**. 문장이 곧 자막 한 줄이 됩니다.

```text
커피 한 잔이 당신의 하루를 바꾼다면 믿으시겠습니까? 지금부터 30초만 집중해 보세요.

첫째, 카페인은 뇌의 피로 신호를 차단합니다. …

…
```

**③ 전체 자동 조립**

```bash
python build.py all --bgm assets/bgm/lofi.mp3 --watermark "@mychannel"
```

**④ 결과 확인** → `output/final.mp4` (+ `output/subtitles.srt`)

---

## 2-1. 🌐 웹 UI로 실행 (Flask)

대본을 브라우저에 붙여 넣고 결과 파일을 바로 받고 싶다면:

```bash
pip install -r requirements.txt   # Flask 포함
python webapp.py --host 0.0.0.0 --port 5000
```

브라우저에서 `http://localhost:5000` 접속 → 대본 입력(+미디어/BGM 업로드, 음성·Whisper 모델·워터마크 선택) → **🎬 영상 생성** → 진행률·실시간 로그 확인 → **final.mp4 다운로드**.

| API | 설명 |
|---|---|
| `GET /` | 생성 폼 페이지 |
| `POST /api/generate` | 작업 생성 (multipart: script, media[], bgm, 옵션들) → `{job_id}` |
| `GET /api/jobs/<id>` | 상태/진행률/로그 폴링 |
| `GET /api/jobs` | 최근 작업 목록 |
| `GET /api/download/<id>/video` · `/srt` | 결과 파일 다운로드 |

- 작업은 `jobs/<job_id>/` 폴더에 격리 저장(입력/중간산출물/결과)
- 백그라운드 워커 1개가 대기열을 순차 처리(FFmpeg/Whisper 동시 실행 방지)
- ⚡ **급속 미리보기**: "오버레이 생략" 체크 시 Remotion 없이 베이스+오디오만 빠르게 조립 (`build.py --no-overlay`와 동일)
- ⚠️ 인증이 없으므로 개인/로컬/팀 납품용으로만 사용하세요.

---

## 2-2. ✨ AI 대본 자동 생성 (주제 → 대본)

주제만 던지면 **관리자가 미리 다듬어 둔 프롬프트**로 파이프라인 규격(빈 줄=씬, 문장부호=자막 분할)에 맞는 대본을 생성합니다.

**관리자 설정 파일**

| 파일 | 역할 |
|---|---|
| `admin/scene_pack_prompt.txt` | ⭐ 씬 팩 프롬프트 — 주제 → 대본+씬별 이미지/동영상 프롬프트(JSON 계약). 키 이름(`scenes/narration/image_prompt/video_prompt`)은 파서가 찾는 이름이니 바꾸지 마세요 |
| `admin/media_prompt.txt` | ⭐ 완성된 대본 → 씬별 미디어 프롬프트만(JSON 배열 계약). `image_prompt`/`video_prompt` 키 고정 |
| `admin/script_prompt.txt` | 대본 전용 레거시 템플릿(기존 호환) — 치환 변수: `{topic}` `{scene_count}` `{duration}` `{tone}` (`{media_lang}` `{scenes}`도 사용 가능) |
| `admin/llm.json` | LLM 연결 설정. `admin/llm.local.json`(git 미추적)이 있으면 우선 |

**LLM 설정 (`admin/llm.json`)**

```json
{
  "provider": "openai-compatible",   // OpenAI / Ollama / LM Studio 등
  "model": null,                      // null → OPENAI_MODEL → gpt-4o-mini
  "base_url": null,                   // 로컬: "http://localhost:11434/v1" 등
  "api_key_env": "OPENAI_API_KEY",    // 키는 환경변수로만 (파일에 저장 금지)
  "temperature": 0.8,
  "max_tokens": 1200
}
```

- `"provider": "mock"` — 네트워크 없이 형식 검증/시연용 대본 생성
- API 키: `export OPENAI_API_KEY=...` (또는 `api_key_env`에 지정한 변수)

**CLI 사용**

```bash
python build.py scriptgen --topic "카페인의 과학" --scenes 4 --duration 30
# → assets/script.txt 로 저장(기본) → 이어서 python build.py all
```

**웹 UI 사용**: 페이지 상단 "AI 대본 생성" 칸에 주제 입력 → ✨ 대본 생성 → 대본 칸에 자동 입력(검토·수정 가능) → 바로 🎬 영상 생성.

**씬 팩 출력**: `scriptgen` 은 대본 외에 씬별 **이미지/동영상 생성 프롬프트**도 함께 만들어 `<out-dir>/media_prompts.json` + `.txt` 로 저장합니다. 흐름은:
① 프롬프트 복사 → ② 사용 중인 영상/이미지 생성 AI 도구에 붙여넣어 씬별 미디어 생성 → ③ `assets/media/01_…`, `02_…` 로 저장 → ④ `python build.py all`.
시각 프롬프트 언어는 `--media-lang English`(기본)로 지정합니다. (웹 UI에서는 씬별 복사 버튼 + 전체 TXT 다운로드 제공)

**완성된 대본(직접 입력/다른 AI) → 프롬프트만**:

```bash
python build.py mediaprompts --script assets/script.txt
```

씬 순서 그대로 `media_prompts.(json|txt)` 생성. 웹 UI의 **🖼️ 미디어 프롬프트** 버튼 동일 흐름.

생성된 출력은 자동 정제됩니다(마크다운 펜스/번호·"씬 N:" 접두어 제거, 문장 종결 보정, 씬 블록 검증) — 파서가 못 읽는 형식이면 오류로 알려줍니다.

---

## 3. 파이프라인 단계 (개별 실행 가능)

| 단계 | 명령 | 하는 일 | 산출물 |
|---|---|---|---|
| scriptgen | `python build.py scriptgen --topic …` | 주제 → 대본(빈 줄=씬) + 씬별 이미지/동영상 프롬프트 | `script.txt`, `media_prompts.(json\|txt)` |
| mediaprompts | `python build.py mediaprompts` | 완성 대본 → 씬별 미디어 프롬프트만 | `media_prompts.(json\|txt)` |
| prepare | `python build.py prepare` | 대본 파싱 + 미디어 수집/매칭/길이 분석 | `work/prep.json` |
| audio | `python build.py audio` | 씬별 나레이션 TTS 생성 | `work/audio/scene_XX.mp3` |
| timeline | `python build.py timeline` | 프레임 단위 절대시간 타임라인 + 나레이션 마스터 | `work/timeline.json`, `work/narration_full.wav` |
| subs | `python build.py subs` | Whisper word-timestamp → 대본 문장 정렬(karaoke 토큰 포함) | `timeline.json` 갱신, `output/subtitles.srt` |
| base | `python build.py base` | 씬별 1080x1920@30 세그먼트 정규화 → concat | `work/base.mp4` |
| overlay | `python build.py overlay` | Remotion 투명 배경 그래픽 렌더 | `work/overlay.webm` |
| mux | `python build.py mux` | 오버레이 합성 + 나레이션/BGM 덕킹 + faststart | `output/final.mp4` |
| all | `python build.py all` | 위 전부 순차 실행 | 〃 |

중간 산출물이 파일로 이어지므로, **자막만 다시 뽑고 싶으면 `subs` 이후 단계만 재실행**하면 됩니다(캐시 재사용).

---

## 4. 핵심 기능

### 🎙 나레이션 (TTS)

**① Qwen3-TTS — 로컬 고품질 (권장, 한국어 Sohee)**

```bash
pip install -U qwen-tts                      # torch는 CUDA 버전에 맞게 설치 권장
python build.py audio --tts-backend qwen     # 최초 1회 모델 다운로드(수 GB)
```

| 항목 | 옵션 |
|---|---|
| 스피커 | `--qwen-speaker Sohee`(기본, 한국어 감성 여성) 외 8개 프리셋(Ryan·Aiden·…) |
| 톤 지시 | `--qwen-instruct "차분하고 신뢰감 있는 낭독"` (CustomVoice/VoiceDesign) |
| 모델 | `…-1.7B-CustomVoice`(기본) · `…-0.6B-CustomVoice`(경량) · `…-1.7B-VoiceDesign` · `…-*-Base`(클론) |
| 보이스 클론 | `--qwen-model Qwen/Qwen3-TTS-12Hz-1.7B-Base --qwen-ref-audio my_voice.mp3 --qwen-ref-text "레퍼런스 대사"` |
| 디바이스 | `--qwen-device auto\|cpu\|cuda:0` (GPU 없으면 자동 cpu) |

**② 엔진 체인 (`--tts-backend`)** — auto 기본값은 `qwen → edge → gtts` 순 자동 평활(미설치/실패 시 다음으로):

| 값 | 의미 |
|---|---|
| `auto` | qwen → edge → gtts (권장) |
| `qwen` | Qwen3-TTS만 사용 |
| `qwen,edge` | 로컬 우선 + 클라우드 평활 |
| `edge` / `gtts` | 클라우드 신경망 / 경량 |

**③ edge-tts 음성 (`--voice`)** — qwen 미사용 시 적용
- 외부 목소리(다른 TTS/직접 녹음)를 쓰고 싶다면:

```bash
assets/narration/scene_00.mp3   # ← 씬 번호로 넣으면 TTS를 건드리지 않고 그대로 사용
assets/narration/scene_01.mp3
```

**한국어 edge 음성 예시** (`--voice`)
| 음성 | 특징 |
|---|---|
| `ko-KR-SunHiNeural` (기본) | 밝은 여성, 정보 전달 |
| `ko-KR-InJoonNeural` | 차분한 남성 |
| `ko-KR-HyunsuMultilingualNeural` | 다국어 남성 |
| `ko-KR-JiMinNeural` | 캐주얼 여성 |

속도 조절: `--rate "+10%"` / `--rate "-5%"`

### 📝 자막 타이밍 (Whisper Forced Alignment)
- `faster-whisper`를 **씬 단위로** 전사(드리프트 원천 차단) → `word_timestamps=True`
- Whisper 단어 ↔ 대본 문장을 문자 매칭으로 정렬 → **자막 텍스트는 대본과 100% 일치**
- 문장 안 토큰(단어)별 시각까지 계산 → Remotion에서 **karaoke 하이라이트**
- 모델: `--whisper-model tiny|base|small|medium|large-v3` (기본 `base`, 정확도↑ `small` 이상 권장)
- Whisper를 못 쓰는 환경이면: `--no-whisper` (문장 길이 비례 배분으로 자동 평활)

### 🎨 Remotion 그래픽 오버레이
`work/overlay.webm` (VP9 + 알파, 투명 배경)으로 렌더되는 요소:
- **자막**: 굵은 고딕 + 스트로크, 문장 전환 시 spring 팝인, 토큰 karaoke(노란색 `#FFE14D`)
- **상단 진행바**, **하단 가독성 그라데이션**, **워터마크**(`--watermark`)
- 길이/fps/해상도는 `timeline.json`에서 자동 결정 → 베이스 영상과 **프레임 단위 일치**
- 스튜디오 미리보기/실시간 편집: `npm run remotion:studio`
- 무손실급 오버레이: `--overlay-codec prores` (ProRes 4444 MOV)

> 자막 스타일(크기/색/위치)은 `remotion/src/ShortsOverlay.tsx` 한 곳에서 수정합니다.
> 한국어 폰트는 시스템의 `Pretendard / Noto Sans KR / 맑은 고딕` 순으로 적용됩니다.

### 🛠 FFmpeg 조립
- 비디오 클립: cover 크롭으로 9:16 정규화, **짧으면 자동 반복**, 길면 트림
- 이미지: 3배 해상도에서 zoompan **Ken Burns 줌인**(떨림 억제)
- 세그먼트 동일 파라미터 인코딩 → concat 시 **무재인코딩** 고속 병합
- BGM: 총 길이만큼 자동 반복 + `sidechaincompress` **덕킹**(나레이션 구간 자동 감쇠)
- `--loudnorm`: EBU R128(-14 LUFS) 정규화, `+faststart`로 업로드 최적화

---

## 5. 주요 옵션

```text
--voice / --rate            TTS 음성 / 속도
--padding 0.40              씬 끝 여백(호흡)
--whisper-model base        자막 정확도/속도 트레이드오프
--no-whisper                Whisper 없이 비례 자막
--bgm / --bgm-volume 0.2    배경음악 / 음량
--no-duck / --loudnorm      덕킹 끄기 / 정규화 켜기
--watermark "@id"           상단 워터마크
--overlay-codec vp9|prores  오버레이 품질
--fps / --width / --height  규격 변경(기본 30 / 1080 / 1920)
--narration-dir             사전 녹음 나레이션 폴더
```

전체: `python build.py --help`

---

## 6. 폴더 구조

```
.
├── build.py                 # 오케스트레이터 (단계별/전체 실행)
├── pipeline/                # Python 파이프라인
│   ├── script_parser.py     # 대본 → 씬/문장
│   ├── narration.py         # TTS + 나레이션 마스터 트랙
│   ├── timestamps.py        # Whisper 정렬 + karaoke 토큰 + SRT
│   ├── timeline.py          # 프레임 양자화 절대시간 타임라인(JSON)
│   ├── base_video.py        # FFmpeg 세그먼트/concat (Ken Burns, cover)
│   ├── remotion_render.py   # Remotion CLI 러너 (투명 오버레이)
│   └── mux.py               # 오버레이 합성 + 오디오 덕킹 + 최종 인코딩
├── remotion/                # React(Remotion) 오버레이 앱
│   └── src/
│       ├── Root.tsx         # calculateMetadata가 timeline.json 자동 반영
│       └── ShortsOverlay.tsx# 자막/진행바/워터마크 (스타일 수정 지점)
├── assets/
│   ├── script.txt           # ★ 대본 (빈 줄 = 씬, scriptgen 출력 경로)
│   ├── media/               # ★ 생성한 이미지/비디오 (번호 = 순서)
│   ├── narration/           # (선택) 사전 녹음 나레이션 scene_XX.mp3
│   └── bgm/                 # (선택) 배경음악
├── admin/
│   ├── scene_pack_prompt.txt# ★ 씬 팩(대본+미디어 프롬프트) 템플릿
│   ├── media_prompt.txt     # ★ 완성 대본 → 미디어 프롬프트 템플릿
│   ├── script_prompt.txt    # (레거시) 대본 전용 템플릿
│   └── llm.json             # LLM 연결 설정 (로컬: llm.local.json)
├── work/                    # 중간 산출물(자동, git 무시)
└── output/                  # final.mp4 + subtitles.srt
```

---

## 7. 반복 양산 워크플로 (꿀팁)

1. 콘텐츠 1편당 폴더 하나로 관리: `python build.py all --script eps/03.txt --media-dir eps/03/media --work-dir work/ep03 --out-dir out/ep03`
2. 목소리/자막 스타일은 고정(브랜드), 대본과 미디어 소재만 교체
3. 자막이 어색하면 `output/subtitles.srt`로 확인 → 대본 문장 길이 조절 후 `python build.py subs`부터 재실행
4. Remotion Studio(`npm run remotion:studio`)로 자막 디자인을 실시간 프리뷰

---

## 8. 테스트 및 품질

```bash
python tests/test_pipeline.py     # 단위 테스트 (네트워크 불필요): 파서/양자화/Whisper 정렬 수학
python build.py all               # E2E (사전 녹음 나레이션 자동 인식 시 네트워크 없이도 동작)
npm run typecheck                 # Remotion TS 타입체크
npm run remotion:render           # 오버레이만 수동 렌더
```

## 9. 트러블슈팅

| 증상 | 해결 |
|---|---|
| Remotion 렌더가 Chrome 오류로 실패 | `npm run browser:ensure` (최초 1회 Headless Shell 다운로드, 회사 방화벽이면 수동 크롬 경로 지정) |
| `ffmpeg를 찾을 수 없습니다` | OS 패키지로 설치하거나 `pip install imageio-ffmpeg` |
| 자막이 말보다 늦게/빨리 나옴 | `--whisper-model small` 이상으로 정확도 상승, 씬 문장을 더 짧게 |
| 한글 자막이 네모(□)로 깨짐 | Noto Sans KR/Pretendard 폰트를 OS에 설치 |
| TTS 연결 실패 | 네트워크가 막힌 환경이면 `assets/narration/`에 녹음 mp3를 넣고 재실행 (TTS 자동 생략) |
| Qwen3-TTS 로드 실패 | `pip install -U qwen-tts` + torch 설치 확인, VRAM 부족 시 `…-0.6B-CustomVoice` 또는 `--qwen-device cpu`, 최초 1회 HF 접속 필요 |
| Qwen 생성이 느림 | CPU 추론은 씬당 수십 초 — GPU(cuda:0) 사용, 또는 0.6B 모델/short 대본 |
| AI 대본 생성 오류(502/키 없음) | `export OPENAI_API_KEY=...` 설정, 로컬 LLM이면 `base_url` 지정, 네트워크 불가 시 provider를 `mock`으로 |
| 생성 대본 형식 오류 | `admin/script_prompt.txt`의 [출력 형식] 규칙(빈 줄=씬, 문장부호 종료)이 지워지지 않았는지 확인 |
| GPU 메모리 부족 | `--whisper-model tiny --whisper-device cpu` |

---
*Built with Python · edge-tts · faster-whisper · Remotion · FFmpeg*

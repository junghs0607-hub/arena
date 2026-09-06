"""합성 미리보기: 자막(번인) + 영상 + 나레이션을 저해상도·빠른 프리셋으로 조립.

목적: Remotion 최종 렌더(무겁고 Node 필요) 전에 "자막/영상/나레이션이
잘 맞물리는지" 몇 초의 미리보기 영상으로 확인.

자막 스타일은 remotion/src/ShortsOverlay.tsx 의 배치를 근사 모사:
  * 흰색 굵은 자막 + 검은 외곽선
  * 하단 안정 영역(전체 높이의 약 16%) 위 정렬  (원본: bottom 300px@1920)
  * 워터마크: 상단 중앙 반투명 + 그림자
카라오케(단어 강조 #FFE14D)/훅 배너/진행바 등 그래픽은 최종 오버레이에서만 표현.

한국어 폰트가 시스템에 없을 수 있으므로 자막 폰트를 자동 해석한다:
  명시 경로 → assets/fonts/*.tt[f|f|c]|*.otf → 한국어 폰트 자동 다운로드(최초 1회).
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

from .common import fail, find_binary, log, run, warn
from .config import Settings

FONT_DIR = Path("assets/fonts")

# 한국어 오픈 라이센스 폰트 소스 (OFL/IPA/상업 사용 허용 계열)
# - (kind="plain"): .ttf 직접 다운로드
# - (kind="tar.gz"): 저장소 tarball에서 해당 파일만 추출 (raw.githubusercontent 네트워크 차단 대비)
FONT_SOURCES = [
    ("plain", "NanumBarunGothicBold.ttf",
     "https://github.com/hiun/NanumBarunGothic/raw/master/NanumBarunGothicBold.ttf"),
    ("tar.gz", "NanumBarunGothicBold.ttf",
     "https://codeload.github.com/hiun/NanumBarunGothic/tar.gz/refs/heads/master"),
]


def _download_plain(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "shorts-assembler"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = resp.read()
    if len(data) < 100_000:
        raise ValueError("응답이 너무 작습니다(폰트 아님)")
    dest.write_bytes(data)


def _download_from_tarball(url: str, name: str, dest: Path) -> None:
    import io
    import tarfile

    req = urllib.request.Request(url, headers={"User-Agent": "shorts-assembler"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        blob = resp.read()
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        member = next((m for m in tf.getmembers() if m.name.endswith(name)), None)
        if member is None:
            raise ValueError(f"tarball 안에 {name} 없음")
        fh = tf.extractfile(member)
        assert fh is not None
        data = fh.read()
    if len(data) < 100_000:
        raise ValueError("폰트 파일이 손상(너무 작음)")
    dest.write_bytes(data)


def resolve_subtitle_font(explicit: str | Path | None = None) -> Path | None:
    """1) 명시 경로 → 2) assets/fonts → 3) 자동 다운로드. 실패 시 None(경고)."""
    if explicit:
        p = Path(explicit)
        if p.exists():
            log(f"  자막 폰트(지정): {p}")
            return p
        fail(f"자막 폰트를 찾을 수 없습니다: {explicit}")

    FONT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("*.ttf", "*.otf", "*.ttc"):
        found = sorted(FONT_DIR.glob(ext))
        if found:
            log(f"  자막 폰트(로컬): {found[0]}")
            return found[0]

    for kind, name, url in FONT_SOURCES:
        dest = FONT_DIR / name
        try:
            log(f"  자막 폰트 다운로드 중… {url.split('//', 1)[1][:60]}")
            if kind == "plain":
                _download_plain(url, dest)
            else:
                _download_from_tarball(url, name, dest)
            log(f"  자막 폰트 저장: {dest} ({dest.stat().st_size // 1024} KB)")
            return dest
        except Exception as e:  # noqa: BLE001
            warn(f"자막 폰트 다운로드 실패({url[-45:]}): {str(e)[:120]}")
            dest.unlink(missing_ok=True)
    warn("한국어 폰트를 구하지 못했습니다. 시스템 기본 폰트로 시도합니다. "
         "(한글이 □로 보이면 assets/fonts/에 .ttf를 넣어 주세요)")
    return None


def _vf_unquote_path(p: Path) -> str:
    """ffmpeg 필터 인자 안의 파일 경로 이스케이프."""
    s = str(p.absolute())
    for ch in ("'", "\\", ":", "[", "]", ",", ";"):
        s = s.replace(ch, "\\" + ch)
    return s


def _audio_graph(s: Settings, dur: float, narr_i: int, bgm_i: int | None) -> tuple[str, str]:
    """나레이션 + (선택) BGM 덕킹 믹스 그래프. mux_final과 동일 철학."""
    graph = ""
    narr = f"[{narr_i}:a]"
    if bgm_i is not None and s.bgm_path:
        graph += f"[{bgm_i}:a]atrim=0:{dur:.4f},asetpts=PTS-STARTPTS,volume={s.bgm_volume:.3f}[bg];"
        if s.duck_bgm:
            graph += (
                f"[bg]{narr}sidechaincompress=threshold=0.02:ratio=8:attack=25:release=400:makeup=1[bgd];"
                f"{narr}[bgd]amix=inputs=2:duration=first:normalize=0[a]"
            )
        else:
            graph += f"{narr}[bg]amix=inputs=2:duration=first:normalize=0[a]"
    else:
        graph += f"{narr}anull[a]"
    return graph, "a"


def _hms(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    sc = sec % 60
    return f"{h}:{m:02d}:{sc:05.2f}"


def _font_family(font_path: Path | None) -> str:
    """TTF/OTF의 internal family 이름 추출 (sfnt name 테이블 직접 파싱).

    외부 CLI(fc-scan 등)에 의존하지 않는다 — nameID=1, Windows/Unicode 레코드 우선.
    """
    if font_path is None:
        return "Sans"
    try:
        import struct

        data = font_path.read_bytes()
        if data[:4] == b"ttcf":  # TrueType Collection — 첫 폰트 오프셋으로
            offset0 = struct.unpack(">L", data[12:16])[0]
            data = data[offset0:]
        num_tables = struct.unpack(">H", data[4:6])[0]
        name_off = None
        for i in range(num_tables):
            rec = 12 + i * 16
            if data[rec:rec + 4] == b"name":
                name_off = struct.unpack(">L", data[rec + 8:rec + 12])[0]
                name_len = struct.unpack(">L", data[rec + 12:rec + 16])[0]
                break
        if name_off is None:
            return "Sans"
        base = name_off
        name_data = data[base:base + name_len]
        _, count, str_off = struct.unpack(">HHH", name_data[:6])
        best, any_rec = None, None
        for i in range(count):
            r = 6 + i * 12
            pid, eid, _lid, nid, ln, off = struct.unpack(">HHHHHH", name_data[r:r + 12])
            if nid != 1:
                continue
            raw = name_data[str_off + off: str_off + off + ln]
            txt = None
            try:
                txt = raw.decode("utf-16-be") if pid in (0, 3) else raw.decode("latin-1")
            except Exception:  # noqa: BLE001
                continue
            txt = txt.strip().replace("\x00", "")
            if not txt:
                continue
            if any_rec is None:
                any_rec = txt
            if pid == 3:  # Windows 플랫폼 우선
                best = txt
                break
        return best or any_rec or "Sans"
    except Exception:  # noqa: BLE001
        return "Sans"


def _ass_header(s: Settings, family: str, style_defs: str) -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        f"PlayResX: {s.width}\n"
        f"PlayResY: {s.height}\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + style_defs
        + "\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


_SUB_STYLE_FMT = (
    "Style: SUB, {family}, {size}, &H00FFFFFF, &H000000FF, &H00000000, &H80000000, "
    "-1, 0, 0, 0, 100, 100, 0, 0, 1, 2, 1, 2, 30, 30, {margin_v}, 1"
)
_WM_STYLE_FMT = (
    "Style: WM, {family}, {size}, &H85FFFFFF, &H000000FF, &H80000000, &H00000000, "
    "0, 0, 0, 0, 100, 100, 0, 0, 1, 1, 2, 8, 10, 10, {margin_top}, 1"
)


def _clean_event_text(text: str) -> str:
    return text.replace("\n", "\\N").replace("{", "(").replace("}", ")")


def _subs_ass(timeline: dict, s: Settings, family: str) -> Path:
    """timeline의 subtitles → PlayRes 일치 ASS (SRT 직접 번인의 폰트 크기 배율 문제 회피)."""
    margin_v = max(16, round(s.height * (300 / 1920)))
    font_size = max(12, round(s.height * (72 / 1920)))
    style = _SUB_STYLE_FMT.format(family=family, size=font_size, margin_v=margin_v)
    events = []
    for sub in timeline.get("subtitles", []):
        events.append(
            f"Dialogue: 0,{_hms(sub['start'])},{_hms(sub['end'])},SUB,,0,0,0,,"
            + _clean_event_text(sub["text"])
        )
    path = s.work_dir / "subtitles_preview.ass"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_ass_header(s, family, style) + "\n".join(events) + "\n", encoding="utf-8")
    return path


def _watermark_ass(s: Settings, dur: float, family: str) -> Path:
    """상단 중앙 반투명 워터마크용 임시 ASS (원본 오버레이 스타일 근사)."""
    font_size = max(10, round(s.height * (36 / 1920)))
    margin_top = max(10, round(s.height * (40 / 1920)))
    style = _WM_STYLE_FMT.format(family=family, size=font_size, margin_top=margin_top)
    text = s.watermark.replace("\n", " ").replace("{", "(").replace("}", ")")
    events = f"Dialogue: 0,0:00:00.00,{_hms(dur)},WM,,0,0,0,,{text}"
    path = s.work_dir / "watermark.ass"
    path.write_text(_ass_header(s, family, style) + events + "\n", encoding="utf-8")
    return path


def run_preview(timeline: dict, s: Settings, *, font: str | Path | None = None,
                crf: int = 30) -> Path:
    """베이스 + 자막 번인 + 나레이션(+BGM) → out_dir/preview.mp4."""
    ffmpeg = find_binary("ffmpeg")
    if not ffmpeg:
        fail("ffmpeg를 찾을 수 없습니다.")
    dur = float(timeline["total_duration"])
    s.out_dir.mkdir(parents=True, exist_ok=True)
    out = s.out_dir / "preview.mp4"

    font_path = resolve_subtitle_font(font)
    family = _font_family(font_path)
    if font_path:
        log(f"  자막 폰트 패밀리: {family}")

    # ── 자막 번인 필터 (ShortsOverlay 배치 근사, PlayRes=영상 크기) ──
    subs_ass = _subs_ass(timeline, s, family)
    vf_parts = [
        f"subtitles='{_vf_unquote_path(subs_ass)}'"
        + (f":fontsdir='{_vf_unquote_path(font_path.parent)}'" if font_path else "")
    ]
    # 워터마크: 일부 ffmpeg 빌드에 drawtext 가 없으므로 ASS 레이어 하나 더 겹침
    wm_ass = _watermark_ass(s, dur, family) if s.watermark else None
    if wm_ass:
        if font_path:
            vf_parts.append(
                f"subtitles='{_vf_unquote_path(wm_ass)}':fontsdir='{_vf_unquote_path(font_path.parent)}'"
            )
        else:
            vf_parts.append(f"subtitles='{_vf_unquote_path(wm_ass)}'")

    inputs: list[str] = ["-i", str(s.base_video_path), "-i", str(s.narration_path)]
    bgm_i: int | None = None
    if s.bgm_path and Path(s.bgm_path).exists():
        inputs += ["-stream_loop", "-1", "-i", str(s.bgm_path)]
        bgm_i = 2

    audio_graph, a_label = _audio_graph(s, dur, 1, bgm_i)
    graph = f"[0:v]{','.join(vf_parts)},format=yuv420p[v];{audio_graph}"

    run(
        [
            ffmpeg, "-y", *inputs,
            "-filter_complex", graph,
            "-map", "[v]", "-map", f"[{a_label}]",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", "-t", f"{dur:.4f}",
            str(out),
        ],
        desc="합성 미리보기 조립 (자막 번인 + 나레이션 먹스)",
    )
    log(f"👀 미리보기: {out} ({out.stat().st_size // 1024} KB, {dur:.2f}s)")
    return out

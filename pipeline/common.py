"""공용 유틸: 로깅, 외부 바이너리 탐색, subprocess 래퍼."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def log(msg: str) -> None:
    print(f"[pipeline] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[pipeline][경고] {msg}", file=sys.stderr, flush=True)


def fail(msg: str) -> None:
    print(f"[pipeline][오류] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def find_binary(name: str) -> str | None:
    """ffmpeg/ffprobe 실행 파일을 찾는다.

    우선순위: 환경변수(FFMPEG_BIN/FFPROBE_BIN) → PATH → imageio-ffmpeg(ffmpeg만).
    """
    env_key = f"{name.upper()}_BIN"
    if os.environ.get(env_key):
        return os.environ[env_key]
    found = shutil.which(name)
    if found:
        return found
    if name == "ffmpeg":
        try:  # pip install imageio-ffmpeg 로 깔리는 정적 바이너리 폭풍우 대비책
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    return None


def run(cmd: list[str], *, desc: str = "", quiet: bool = True) -> subprocess.CompletedProcess:
    """subprocess 실행 + 실패 시 친절한 에러."""
    if desc:
        log(f"$ {desc}")
    log("  " + " ".join(str(c) for c in cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-3000:]
        fail(f"명령 실행 실패 ({desc or cmd[0]})\n{tail}")
    if not quiet and proc.stderr:
        print(proc.stderr)
    return proc


def natural_key(p: Path):
    """파일명 자연 정렬 키: 선행 숫자를 정수로 비교 (01_, 2_, 10_ 순)."""
    import re

    stem = p.stem
    m = re.match(r"\s*(\d+)", stem)
    if m:
        return (0, int(m.group(1)), stem)
    return (1, 0, stem.lower())

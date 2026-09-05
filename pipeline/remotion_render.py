"""Remotion 그래픽 오버레이 렌더 러너.

자막(karaoke 하이라이트), 진행바, 워터마크를 '투명 배경' 영상으로 렌더한다.
  * vp9   → overlay.webm (yuva420p, 용량/호환 균형)
  * prores→ overlay.mov  (yuva444p10le, 무손실급 품질)
Remotion 쪽 Composition(calculateMetadata)이 timeline.json을 읽어
fps/해상도/총 프레임을 자동 결정하므로 길이 불일치가 없다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .common import fail, log, run, warn
from .config import Settings


def find_project_root(s: Settings) -> Path:
    """package.json이 있는 리포 루트 탐색 (work_dir의 상위들 중)."""
    here = Path(__file__).resolve().parent.parent
    if (here / "package.json").exists():
        return here
    return Path.cwd()


def write_props(s: Settings, root: Path) -> Path:
    """Remotion이 읽을 수 있게 timeline.json을 public/ 로 복사하고 props를 쓴다.

    (Remotion 번들은 브라우저 컨텍스트에서 평가되므로 fs 직접 접근 대신
     staticFile('timeline.json') + fetch 패턴을 사용한다.)
    """
    import shutil

    public_dir = root / "remotion" / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(s.timeline_path, public_dir / "timeline.json")
    props = {"timelinePath": "timeline.json"}
    props_path = s.work_dir / "remotion_props.json"
    props_path.write_text(json.dumps(props), encoding="utf-8")
    return props_path


def ensure_node_modules(root: Path) -> None:
    if (root / "node_modules").exists():
        return
    if not shutil.which("npm"):
        fail("npm이 없습니다. Node.js 18+ 를 설치하세요.")
    log("node_modules 없음 → npm install 실행 (최초 1회)")
    proc = subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund"],
        cwd=root, capture_output=True, text=True,
    )
    if proc.returncode != 0:
        fail(f"npm install 실패:\n{proc.stderr[-2000:]}")


def render_overlay(s: Settings, timeline: dict) -> Path:
    root = find_project_root(s)
    ensure_node_modules(root)
    props_path = write_props(s, root)

    entry = "remotion/src/index.ts"
    out_name = s.overlay_path.name
    if s.overlay_codec == "prores":
        # Remotion 4 정식 스펙: --codec=prores + --prores-profile=4444 (알파 채널)
        codec_args = ["--codec=prores", "--prores-profile=4444", "--pixel-format=yuva444p10le"]
    else:
        codec_args = ["--codec=vp9", "--pixel-format=yuva420p"]

    cmd = [
        "npx", "remotion", "render", entry, "ShortsOverlay",
        str(s.overlay_path), *codec_args,
        f"--props={props_path}",
        "--overwrite", "--log=info",
    ]
    log("Remotion 오버레이 렌더 시작 (투명 배경)")
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stdout + "\n" + proc.stderr)[-4000:]
        fail(
            "Remotion 렌더 실패. (최초 실행 시 Chrome Headless Shell 다운로드가 필요합니다:\n"
            "  npx remotion browser ensure\n)\n" + tail
        )
    if not s.overlay_path.exists():
        fail(f"오버레이 산출물이 없습니다: {s.overlay_path}")
    log(f"  {out_name} 완성 ({s.overlay_path.stat().st_size//1024} KB)")
    return s.overlay_path

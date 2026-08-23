#!/usr/bin/env python3

"""把 docs/panels/ 的展示面板截成 README 用的 PNG。

先跑 scripts/make_panel_demo.py 產生面板，這支再把它們一張張截下來。
資料是 make_panel_demo.py 那份寫死的示範資料，不含任何真實用量。

Chrome 無頭模式有最小視窗寬度，直接把 --window-size 設成面板寬度會讓內容
按更寬的版面排好、截圖畫布卻只有面板寬，右邊整條被裁掉。所以這裡開一個
比較寬的視窗，用 wrapper 把面板放進固定寬度的 iframe 並置中，截完再用
macOS 內建的 sips 從中心裁回面板尺寸。

用法：.venv/bin/python scripts/make_panel_shots.py [輸出目錄]
預設輸出到 docs/，英文存成 <id>.en.png、繁中存成 <id>.png，沿用既有命名。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PANELS_DIR = _REPO_ROOT / "docs" / "panels"
# 截圖時的視窗要明顯寬於面板，才不會撞到無頭模式的最小寬度。
SHOT_VIEWPORT_WIDTH = 900
# 既有截圖的命名慣例：英文帶 .en，繁中不帶。
LANGUAGE_SUFFIXES = {"en": ".en", "zh-TW": ""}

WRAPPER = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; height: 100%; background: transparent; }}
  body {{ display: grid; place-items: center; }}
  iframe {{ width: {width}px; height: {height}px; border: 0; display: block; }}
</style></head>
<body><iframe src="{src}" scrolling="no"></iframe>
<script>
  window.addEventListener("message", function (event) {{
    var height = event.data && event.data.usagePanelHeight;
    if (height) document.querySelector("iframe").style.height = height + "px";
  }});
  document.querySelector("iframe").addEventListener("load", function () {{
    this.contentWindow.postMessage({{ usageDemoLanguage: "{language}" }}, "*");
  }});
</script>
</body></html>
"""


def _capture(wrapper: Path, out: Path, width: int, height: int) -> None:
    subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={SHOT_VIEWPORT_WIDTH},{height}",
            f"--screenshot={out}",
            "--virtual-time-budget=4000",
            wrapper.as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    # sips 的 -c 是從中心裁，wrapper 已經把面板置中了。
    subprocess.run(
        ["sips", "-c", str(height), str(width), str(out), "--out", str(out)],
        check=True,
        capture_output=True,
    )


def main() -> int:
    if not CHROME.exists():
        print(f"error: {CHROME} not found", file=sys.stderr)
        return 1
    if shutil.which("sips") is None:
        print("error: sips not found (this script is macOS-only)", file=sys.stderr)
        return 1

    index_path = PANELS_DIR / "panels.json"
    if not index_path.exists():
        print(f"error: {index_path} missing — run make_panel_demo.py first", file=sys.stderr)
        return 1

    out_dir = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _REPO_ROOT / "docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    panels = json.loads(index_path.read_text(encoding="utf-8"))

    # README 用 width="32%" 把截圖三張並排，高度不一就會錯位、留下大片空白
    # （world_cup 812 對上 win95 1055 差了 243px）。全部截成最高的那個尺寸，
    # 面板的 body 是 height: 100vh，拉高後自己的背景會填滿多出來的部分。
    shot_height = max(int(panel["height"]) for panel in panels)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for panel in panels:
            width = int(panel["width"])
            height = shot_height
            for language, suffix in LANGUAGE_SUFFIXES.items():
                wrapper = tmp_dir / f"{panel['id']}{suffix or '.zh'}.html"
                wrapper.write_text(
                    WRAPPER.format(
                        width=width,
                        height=height,
                        src=(PANELS_DIR / f"{panel['id']}.html").as_uri(),
                        language=language,
                    ),
                    encoding="utf-8",
                )
                out = out_dir / f"{panel['id']}{suffix}.png"
                _capture(wrapper, out, width, height)
                print(f"{out.name}: {out.stat().st_size // 1024}KB")

    print(f"{len(panels)} themes x {len(LANGUAGE_SUFFIXES)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent

CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PANELS_DIR = _REPO_ROOT / "docs" / "panels"
# 截圖時的視窗要明顯寬於面板，才不會撞到無頭模式的最小寬度。
SHOT_VIEWPORT_WIDTH = 900
# 既有截圖的命名慣例：英文帶 .en，繁中不帶。
LANGUAGE_SUFFIXES = {"en": ".en", "zh-TW": ""}

# iframe 須固定為傳入高度：面板 body 的 100vh 填滿背景；隨自然高度縮會露出透明 wrapper，截圖成白邊。
WRAPPER = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  html, body {{ margin: 0; height: 100%; background: transparent; }}
  body {{ display: grid; place-items: center; }}
  iframe {{ width: {width}px; height: {height}px; border: 0; display: block; }}
</style></head>
<body><iframe src="{src}" scrolling="no"></iframe>
<script>
  document.querySelector("iframe").addEventListener("load", function () {{
    this.contentWindow.postMessage({{ usageDemoLanguage: "{language}" }}, "*");
  }});
</script>
</body></html>
"""


# 量高度用：面板把 dynamic_height 量到的內容高度 postMessage 給外層，
# 寫進 title 讓 --dump-dom 讀得到。
MEASURE_SCRIPT = """<script>
  addEventListener("message", function (event) {
    var height = event.data && event.data.usagePanelHeight;
    if (height) document.title = String(height);
  });
</script>
"""


def _measure(wrapper: Path) -> float | None:
    # 有動畫的面板（matrix）在虛擬時間下偶爾漏掉回報，量不到就重試。
    for _attempt in range(3):
        result = subprocess.run(
            [
                str(CHROME),
                "--headless=new",
                "--disable-gpu",
                "--virtual-time-budget=4000",
                "--dump-dom",
                wrapper.as_uri(),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        match = re.search(r"<title>([0-9.]+)</title>", result.stdout)
        if match:
            return float(match.group(1))
    return None


def _wrapper(
    tmp_dir: Path, panel: dict[str, Any], language: str, height: int, *, measure: bool
) -> Path:
    suffix = LANGUAGE_SUFFIXES[language]
    path = tmp_dir / f"{panel['id']}{suffix or '.zh'}{'.measure' if measure else ''}.html"
    html = WRAPPER.format(
        width=int(panel["width"]),
        height=height,
        src=(PANELS_DIR / f"{panel['id']}.html").as_uri(),
        language=language,
    )
    if measure:
        html = html.replace("</body>", f"{MEASURE_SCRIPT}</body>", 1)
    path.write_text(html, encoding="utf-8")
    return path


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

    # 每張截成面板自己量到的內容高度，跟 app 裡開出來的視窗一樣高。
    # 統一截成最高那張的高度，卡片不會伸長的面板（classic、maple）底下會多一截
    # 空底；README 改用 align="top" 讓同一排頂端對齊。
    # panels.json 是五張完整卡的預設高度，四張以上切成精簡卡後會比實際高，
    # 只拿來量，不拿來截。
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        missing = []
        for panel in panels:
            for language, suffix in LANGUAGE_SUFFIXES.items():
                wrapper = _wrapper(tmp_dir, panel, language, int(panel["height"]), measure=True)
                height = _measure(wrapper)
                if height is None:
                    missing.append(f"{panel['id']} ({language})")
                    continue
                shot_height = math.ceil(height)
                wrapper = _wrapper(tmp_dir, panel, language, shot_height, measure=False)
                out = out_dir / f"{panel['id']}{suffix}.png"
                _capture(wrapper, out, int(panel["width"]), shot_height)
                print(f"{out.name}: {shot_height}px, {out.stat().st_size // 1024}KB")
        if missing:
            print(f"error: no height reported by {', '.join(missing)}", file=sys.stderr)
            return 1

    print(f"{len(panels)} themes x {len(LANGUAGE_SUFFIXES)} languages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""界面预览：起服务 → 灌假数据 → 截图，用来肉眼检查界面。

不联网、不用账号。
跑法：python tests/preview_ui.py
产物：debug/ui_preview.png
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import browser  # noqa: E402
import config  # noqa: E402
import preview_dashboard  # noqa: E402
import server  # noqa: E402

OUT = config.DEBUG_DIR / "ui_preview.png"


def main() -> int:
    config.ensure_dirs()
    port = server.serve(0, open_window=False, block=False)

    sample = preview_dashboard.SAMPLE
    server._set(
        data=sample,
        phase="done",
        message="完成：扫了 4 门课，作业 11 条，需要动手 4 条（耗时 6.8 秒）",
        done=4,
        total=4,
        log=[
            {"t": "14:52:03", "m": "登录态有效，共 14 门课程。", "tag": "ok"},
            {"t": "14:52:03", "m": "跳过 10 门已结课/已归档课程"},
            {"t": "14:52:05", "m": "[1/4] 高等数学 A(2)  作业 4 条，待办 2 条", "tag": "warn"},
            {"t": "14:52:06", "m": "[2/4] 大学英语（三）  作业 3 条，待办 2 条", "tag": "warn"},
            {"t": "14:52:07", "m": "[3/4] 数据结构与算法  作业 3 条，待办 0 条"},
            {"t": "14:52:08", "m": "[4/4] 马克思主义基本原理 —— 失败：没拿到 enc 令牌", "tag": "err"},
        ],
    )

    with browser.open_context(headless=True, profile_dir=browser.preview_profile()) as ctx:
        page = browser.first_page(ctx)
        page.set_viewport_size({"width": 1080, "height": 1500})
        page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
        page.wait_for_timeout(1800)
        page.evaluate("document.querySelectorAll('.course').forEach(function(e){e.classList.add('open')})")
        page.wait_for_timeout(250)
        page.screenshot(path=str(OUT), full_page=True)
    print(f"截图已保存：{OUT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""检查登录态：用程序真实的浏览器目录，只打课程列表接口（最轻的一个）。

跑法：python tests/check_session.py

用途：区分「登录态失效」和「被风控」—— 这两件事的恢复方式完全不同，
以前混在一起看不出所以然。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import browser  # noqa: E402
import config  # noqa: E402
import scanner  # noqa: E402

URL = f"{config.COURSE_LIST_API}?view=json&rss=1"


def probe(ctx, label: str) -> str:
    try:
        resp = ctx.request.get(URL, timeout=config.REQUEST_TIMEOUT_MS,
                               headers=scanner.init_headers(ctx))
        body = resp.text()
    except Exception as exc:  # noqa: BLE001
        return f"{label} → 请求异常：{exc}"
    try:
        data = json.loads(body)
    except Exception:  # noqa: BLE001
        return f"{label} → 不是 JSON（长度 {len(body)}）"
    return (
        f"{label} → result={data.get('result')} "
        f"msg={str(data.get('msg'))[:20]!r} 课程数={len(data.get('channelList') or [])}"
    )


def main() -> int:
    config.ensure_dirs()
    with browser.open_context(headless=True) as ctx:
        cookies = [c for c in ctx.cookies() if "chaoxing" in str(c.get("domain") or "")]
        print(f"浏览器目录里的 chaoxing cookie：{len(cookies)} 条")
        print(probe(ctx, "① 现状"))

        snapshot = None
        if config.STATE_JSON.exists():
            try:
                snapshot = json.loads(config.STATE_JSON.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                snapshot = None
        if snapshot:
            print(f"登录态快照：{len(snapshot.get('cookies') or [])} 条 cookie")
            if snapshot.get("cookies"):
                ctx.add_cookies(snapshot["cookies"])   # 强制覆盖，只为判断快照本身还有没有效
                print(probe(ctx, "② 强灌快照后"))
        else:
            print("登录态快照：不存在")

    print()
    print("怎么读：")
    print("  result=1          → 登录态是好的")
    print("  msg='请重新登录'   → 登录态失效了，跑「登录学习通.bat」重新登录")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

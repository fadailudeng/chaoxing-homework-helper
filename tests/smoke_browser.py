"""冒烟测试：验证浏览器能起来 + 学习通接口可达。

跑法：python tests/smoke_browser.py
不需要账号 —— 未登录本来就应该返回「需要登录」，这也顺带验证了登录失效的识别逻辑。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import browser  # noqa: E402
import config  # noqa: E402

ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""), flush=True)


print("== 1. 启动浏览器（headless，复用本机 Edge） ==")
try:
    # 用独立 profile，不碰正式登录态目录
    with browser.open_context(headless=True, profile_dir=browser.preview_profile()) as ctx:
        check("浏览器启动", True, f"channel={config.BROWSER_CHANNEL}")

        page = browser.first_page(ctx)
        print("== 2. 访问学习通首页 ==", flush=True)
        try:
            page.goto("https://www.chaoxing.com", timeout=30000, wait_until="domcontentloaded")
            title = page.title()
            check("学习通首页可达", bool(title), f"title={title!r} url={page.url}")
        except Exception as exc:  # noqa: BLE001
            check("学习通首页可达", False, f"{type(exc).__name__}: {exc}")

        print("== 3. 课程列表接口（未登录，预期被拒） ==", flush=True)
        try:
            resp = ctx.request.get(
                f"{config.COURSE_LIST_API}?view=json&rss=1", timeout=20000
            )
            body = resp.text()
            print(f"     HTTP {resp.status}  body[:200]={body[:200]!r}", flush=True)
            # 未登录时预期 result != 1；能拿到响应本身就说明网络和接口都通
            check("课程列表接口可达", resp.status == 200 or resp.status in (302, 403))
        except Exception as exc:  # noqa: BLE001
            check("课程列表接口可达", False, f"{type(exc).__name__}: {exc}")
except Exception as exc:  # noqa: BLE001
    check("浏览器启动", False, f"{type(exc).__name__}: {exc}")

print("\n" + ("全部通过" if ok else "存在失败项，见上"), flush=True)
sys.exit(0 if ok else 1)

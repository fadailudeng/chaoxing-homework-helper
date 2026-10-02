"""网络层通路诊断（不需要登录）。

跑法：python tests/diagnose_network.py

用途：确认三个接口到底能不能连通、会重定向到哪儿、响应长什么样。
      改完抓取代码后第一时间跑这个 —— 上一版「Failed to fetch」这类问题，
      在这里会一眼看出来，不用等整个扫描跑完。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import browser  # noqa: E402
import config  # noqa: E402
import scanner  # noqa: E402


def _sample_course() -> dict:
    """优先用上次真实扫描留下的课程参数，没有就退回占位值。"""
    try:
        data = json.loads(config.RESULT_JSON.read_text(encoding="utf-8"))
        course = data["courses"][0]
        return {
            "course_id": course["course_id"],
            "class_id": course["class_id"],
            "cpi": course["cpi"],
            "name": course.get("name", "?"),
        }
    except Exception:  # noqa: BLE001
        return {"course_id": "1", "class_id": "2", "cpi": "3", "name": "占位课程"}


def show(label: str, resp, note: str = "") -> str:
    body = resp.text()
    print(f"  {label}", flush=True)
    print(f"    HTTP {resp.status}   长度 {len(body)}", flush=True)
    print(f"    最终地址 {resp.url}", flush=True)
    if note:
        print(f"    {note}", flush=True)
    return body


def main() -> int:
    course = _sample_course()
    print(f"用课程参数：{course['name']} (courseId={course['course_id']})", flush=True)

    with browser.open_context(headless=True, profile_dir=browser.preview_profile()) as ctx:
        scanner.init_headers(ctx)
        print(f"\n请求头 UA = {scanner._HEADERS.get('User-Agent', '(空)')[:70]}...", flush=True)

        print("\n[1] 课程列表接口（未登录时应回 result=0 而不是报错）", flush=True)
        try:
            resp = ctx.request.get(
                f"{config.COURSE_LIST_API}?view=json&rss=1",
                timeout=config.REQUEST_TIMEOUT_MS,
                headers=scanner._HEADERS,
            )
            body = show("GET backclazzdata", resp)
            print(f"    应答前 120 字：{body[:120]}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"    ❌ 请求异常：{type(exc).__name__}: {exc}", flush=True)

        print("\n[2] 课程中间页（上一次的 bug 就出在这一步之后）", flush=True)
        middle = scanner._middle_url(course)
        print(f"    {middle}", flush=True)
        try:
            resp = ctx.request.get(middle, timeout=config.REQUEST_TIMEOUT_MS, headers=scanner._HEADERS)
            body = show("GET stucoursemiddle", resp)
            enc = scanner.extract_work_enc(body, resp.url)
            print(f"    workEnc = {enc or '(未找到 — 未登录时属正常)'}", flush=True)
            if "passport" in resp.url or "请登录" in body[:5000]:
                print("    → 落到了登录页，符合未登录的预期", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"    ❌ 请求异常：{type(exc).__name__}: {exc}", flush=True)

        print("\n[3] 作业列表接口（未登录时应回登录页，而不是抛 Failed to fetch）", flush=True)
        url = (
            f"{config.WORK_LIST_URL}?courseId={course['course_id']}"
            f"&classId={course['class_id']}&cpi={course['cpi']}"
            f"&enc={'0' * 32}&pageNum=1"
        )
        try:
            resp = ctx.request.get(url, timeout=config.REQUEST_TIMEOUT_MS, headers=scanner._HEADERS)
            body = show("GET work/list", resp)
            print(f"    判定是登录页：{scanner.hwparser.looks_like_login_page(body)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"    ❌ 请求异常：{type(exc).__name__}: {exc}", flush=True)

    print("\n结论：上面三条只要都不出现「请求异常」，网络层通路就是通的。", flush=True)
    print("      （未登录时拿不到数据、拿不到 workEnc 都是正常的）", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

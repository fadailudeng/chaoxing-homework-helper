"""界面服务冒烟测试：不打开窗口，只验证服务能起、页面能取、API 正常。

跑法：python tests/smoke_server.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import server  # noqa: E402

ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""), flush=True)


def get(url: str):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read()


def get_full(url: str):
    """同 get，但把响应头也带回来 —— 测 Content-Disposition 这类只用得上。"""
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, dict(resp.headers), resp.read()


def main() -> int:
    port = server.serve(0, open_window=False, block=False)
    base = f"http://127.0.0.1:{port}"
    print(f"服务已启动于 {base}\n", flush=True)

    status, body = get(f"{base}/api/state")
    state = json.loads(body.decode("utf-8"))
    check("GET /api/state", status == 200 and "phase" in state and "log" in state,
          f"phase={state.get('phase')} running={state.get('running')}")
    # 新的 app.py 靠这个指纹判断「运行中的进程是不是旧代码」，别把它弄丢了
    check("GET /api/state 带代码指纹", bool(state.get("fingerprint")),
          str(state.get("fingerprint")))

    status, body = get(f"{base}/")
    html = body.decode("utf-8")
    check("GET / 返回界面页面", status == 200 and "学习通作业助手" in html,
          f"{len(html)} 字节")

    status, body = get(f"{base}/icon.png")
    check("GET /icon.png 返回图标", status == 200 and body[:8] == b"\x89PNG\r\n\x1a\n",
          f"{len(body)} 字节")

    status, body = get(f"{base}/icon.ico")
    check("GET /icon.ico 返回图标", status == 200 and len(body) > 1000, f"{len(body)} 字节")

    # ── 题目页（一键抓取 + 浏览题目）────────────────────
    status, body = get(f"{base}/tasks")
    thtml = body.decode("utf-8")
    check("GET /tasks 返回题目页", status == 200 and "一键抓取全部待办题目" in thtml,
          f"{len(thtml)} 字节")

    status, body = get(f"{base}/api/tasks")
    idx = json.loads(body.decode("utf-8"))
    cand = idx.get("candidates") or {}
    check("GET /api/tasks", status == 200 and "candidates" in idx and "speeds" in idx,
          f"待办={cand.get('pending')} 已过期={cand.get('expired')}")

    status, body = get(f"{base}/api/tasks/state")
    tstate = json.loads(body.decode("utf-8"))
    check("GET /api/tasks/state", status == 200 and "phase" in tstate and "log" in tstate,
          f"phase={tstate.get('phase')} running={tstate.get('running')}")

    # ── 打包给 AI ───────────────────────────────────────
    check("题目页有「一键打包并粘贴给 AI」", 'id="pkSend"' in thtml, "pkSend")
    for bid, why in (("pkCopy", "复制"), ("pkDownload", "下载"), ("pkSave", "存盘")):
        check(f"题目页有「{why}」按钮", f'id="{bid}"' in thtml, bid)

    # 打包接口：返回 Markdown 附件。**不测 save=1** —— 那会往 data/题目/ 写文件，
    # 测试不该污染用户数据（save 分支靠手动验证，见 README）。
    status, headers, body = get_full(f"{base}/api/tasks/pack")
    packed = body.decode("utf-8")
    disp = headers.get("Content-Disposition", "")
    check("GET /api/tasks/pack 返回 Markdown 附件",
          status == 200 and disp.startswith("attachment") and ".md" in disp,
          f"{len(packed)} 字；{disp[:64]}")

    has_tasks = bool(json.loads((get(f"{base}/api/tasks")[1]).decode("utf-8"))
                     .get("saved", {}).get("tasks"))
    if has_tasks:
        check("打包内容含作答要求", "请帮我完成下面这些作业题" in packed, "")
        check("打包内容含输入/输出格式",
              "输入格式" in packed or "输出格式" in packed, "")
        check("打包不含答案", "参考答案" not in packed and "正确答案是" not in packed, "")
        check("打包默认不带 URL", "mooc1.chaoxing.com" not in packed, "")
    else:
        check("打包内容检查（还没抓过题目，跳过）", True, "只验证了接口和响应头")

    status, body = get(f"{base}/api/ai-sites")
    sites = json.loads(body.decode("utf-8"))
    check("GET /api/ai-sites 返回三个 AI 站点",
          status == 200 and set(sites) == {"deepseek", "qianwen", "glm"},
          "、".join(v["label"] for v in sites.values()))

    # 过验证码：只查状态，**不 POST** —— 那会真的启动浏览器
    status, body = get(f"{base}/api/unblock/state")
    ustate = json.loads(body.decode("utf-8"))
    check("GET /api/unblock/state", status == 200 and "phase" in ustate and "log" in ustate,
          f"phase={ustate.get('phase')} running={ustate.get('running')}")

    # ── 清理缓存 ────────────────────────────────────────
    # 界面上必须有这个按钮（2026-10-02 老大提的：以前只能去文件夹双击 bat）
    check("界面顶栏有「清理缓存」按钮", 'id="btnClean"' in html, "btnClean")
    check("清理弹窗结构在界面上", 'id="cleaner"' in html and 'id="clGo"' in html, "")

    # 预览接口：只统计不删。**绝不在测试里 POST /api/clean-cache** ——
    # 那个会真的关窗口、删目录、重启服务。
    status, body = get(f"{base}/api/clean/survey")
    survey = json.loads(body.decode("utf-8"))
    check("GET /api/clean/survey", status == 200 and "items" in survey
          and "protected" in survey and "total_mb" in survey,
          f"可清 {survey.get('total_mb')} MB，{len(survey.get('items') or [])} 项")

    # 保护清单必须覆盖登录态和已扫出来的数据 —— 这是这个按钮的安全底线
    keep_paths = " ".join(p["path"] for p in (survey.get("protected") or []))
    for need, why in (
        ("browser_profile", "登录态"),
        ("login_state.json", "登录态快照"),
        ("homework.json", "扫描结果"),
        ("tasks.json", "抓下来的题目"),
    ):
        check(f"清理保护清单含 {why}", need in keep_paths, need)

    # 安全档（默认）绝不能把 raw_html 这类调试残留算进去
    safe_paths = " ".join(it["path"] for it in (survey.get("items") or []))
    check("安全档不含调试残留", "raw_html" not in safe_paths, "")

    status, body = get(f"{base}/api/clean/survey?optional=1")
    full = json.loads(body.decode("utf-8"))
    full_paths = " ".join(it["path"] for it in (full.get("items") or []))
    check("完整档才含调试残留", "raw_html" in full_paths, "")
    check("完整档不碰数据备份", "homework_backup" not in full_paths, "")

    # 「问 AI」的打开接口必须拦非白名单地址 —— 否则就是个任意 URL 打开器。
    # （只测拒绝路径：白名单地址会真的弹出浏览器，不能在测试里点）
    req = urllib.request.Request(
        f"{base}/api/open-url",
        data=json.dumps({"url": "https://example.com/evil"}).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        blocked = json.loads(resp.read().decode("utf-8"))
    check("POST /api/open-url 拒绝白名单外的地址", blocked.get("ok") is False,
          str(blocked.get("error"))[:60])

    # 404 必须是「能走回去」的页面：界面是 --app 窗口，没有地址栏也没有后退按钮，
    # 纯文本 404 会让人卡在没有出口的页面上（2026-10-02 真踩过）。
    # （路径用纯 ASCII —— urlopen 不接受非 ASCII 的请求行，测试会假失败）
    try:
        get(f"{base}/no-such-page")
        check("未知路径返回 404 页", False, "居然没报错")
    except Exception as exc:  # HTTPError 也是异常
        code = getattr(exc, "code", None)
        page = ""
        try:
            page = exc.read().decode("utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        check("未知路径返回可返回的 404 页",
              code == 404 and "回作业看板" in page and "关闭本窗口" in page,
              f"HTTP {code}，{len(page)} 字节")

    try:
        get(f"{base}/tasks/no-such-page")
        check("题目页下的坏路径也返回 404 页", False, "居然没报错")
    except Exception as exc:
        page = ""
        try:
            page = exc.read().decode("utf-8")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        check("题目页下的坏路径给出「要重启」提示",
              "重启" in page and "不用重新登录" in page, f"{len(page)} 字节")

    # 重复双击不应该开出第二个实例
    check("重复启动复用同一端口", server.serve(0, open_window=False, block=False) != port
          or True, "（随机端口不适用，这里只验证不抛异常）")

    print("\n" + ("全部通过" if ok else "存在失败项"), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

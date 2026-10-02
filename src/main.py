"""学习通作业助手 —— 命令行入口。

用法：
    python src/main.py            # 扫描并打开看板（默认）
    python src/main.py login      # 首次登录 / 登录过期后重新登录
    python src/main.py scan       # 只扫描并更新看板，不打开浏览器
    python src/main.py check      # 检查登录态还有没有效
    python src/main.py dashboard  # 打开上次生成的看板
    python src/main.py unblock    # 被风控要求输图片验证码时：打开浏览器手动过一次

可选参数：
    --max-courses N   本次最多扫 N 门课（默认 150，够覆盖全部课程）
    --skip-retired    跳过标记为已归档的课程。默认**不跳** ——
                      实测那个标记（isretire）不可靠，会把你本学期的课一起漏掉
    --headless        无头模式（更快，但更容易被风控盯上，不推荐）
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import browser  # noqa: E402
import config  # noqa: E402
import parser as hwparser  # noqa: E402
import report  # noqa: E402
import scanner  # noqa: E402


def _parse_args(argv: list[str]) -> tuple[str, dict]:
    opts = {"max_courses": None, "skip_retired": False, "headless": False}
    cmd = "run"
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--max-courses" and i + 1 < len(argv):
            opts["max_courses"] = int(argv[i + 1])
            i += 2
            continue
        if arg.startswith("--max-courses="):
            opts["max_courses"] = int(arg.split("=", 1)[1])
            i += 1
            continue
        if arg == "--skip-retired":
            opts["skip_retired"] = True
        elif arg == "--headless":
            opts["headless"] = True
        elif not arg.startswith("-"):
            cmd = arg
        i += 1
    return cmd, opts


def ensure_login(ctx, *, interactive: bool = True, timeout_sec: int = 900) -> list[dict]:
    """确保处于登录态，返回课程列表。

    未登录时直接在学习通首页等用户手动登录 —— 密码完全不经过本程序。
    interactive=False（如无头模式）时不等待，直接抛错让调用方去引导登录。
    """
    try:
        courses = scanner.fetch_course_list(ctx)
        if courses:
            print(f"登录态有效，共 {len(courses)} 门课程。", flush=True)
            return courses
    except scanner.LoginRequired:
        pass

    if not interactive:
        raise scanner.LoginRequired("登录态无效。无头模式不会等待登录，请先运行「登录学习通.bat」")

    page = browser.first_page(ctx)
    print("=" * 58)
    print("登录态无效或已过期。")
    print(">>> 即将弹出浏览器窗口，请在里面登录学习通（扫码 / 账号密码都行）")
    print(">>> 登录成功后会自动继续，不用回到这个窗口操作。")
    print("=" * 58, flush=True)
    try:
        page.goto(config.HOME_URL, timeout=config.REQUEST_TIMEOUT_MS, wait_until="domcontentloaded")
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + timeout_sec
    dots = 0
    while time.time() < deadline:
        time.sleep(2)
        dots = (dots + 1) % 30
        print("\r等待登录中" + "." * dots + " " * (30 - dots), end="", flush=True)
        try:
            courses = scanner.fetch_course_list(ctx)
            if courses:
                print(f"\r登录成功，共 {len(courses)} 门课程。{' ' * 20}", flush=True)
                # 立刻存一份登录态快照：浏览器被强杀时 profile 里的 cookie 可能还没落盘
                if browser.save_login_state(ctx):
                    print("登录态已保存到本机（以后不用再登，也不上传任何地方）。", flush=True)
                return courses
        except scanner.LoginRequired:
            continue
        except Exception:  # noqa: BLE001
            continue

    print()
    raise scanner.LoginRequired(f"等待登录超过 {timeout_sec // 60} 分钟")


def do_scan(ctx, courses, opts: dict) -> dict:
    return scanner.scan_all(
        ctx,
        courses=courses,
        skip_retired=opts["skip_retired"],
        max_courses=opts["max_courses"],
    )


def finish(result: dict) -> Path:
    scanner.save(result)
    path = report.render(result)
    print(f"看板已生成：{path}", flush=True)
    return path


def cmd_login(opts: dict) -> int:
    with browser.open_context(headless=False) as ctx:
        try:
            ensure_login(ctx)
        except scanner.LoginRequired as exc:
            print(f"登录未完成：{exc}")
            return 1
    print("登录态已保存到本机（不上传任何地方）。以后直接跑「扫描作业.bat」就行。")
    return 0


def cmd_check(opts: dict) -> int:
    with browser.open_context(headless=opts["headless"]) as ctx:
        try:
            courses = scanner.fetch_course_list(ctx)
        except scanner.LoginRequired as exc:
            print(f"登录态无效：{exc}")
            print("请运行「登录学习通.bat」重新登录。")
            return 2
    print(f"登录态有效，共 {len(courses)} 门课程。")
    for c in courses[:10]:
        tag = "" if str(c["is_retired"]) in ("0", "None") else f"  [{c['is_retired']}]"
        print(f"  - {c['name']}  ({c['teacher']}){tag}")
    if len(courses) > 10:
        print(f"  …… 还有 {len(courses) - 10} 门")
    return 0


def cmd_unblock(opts: dict) -> int:
    """被风控要求输验证码时用：把验证码页面直接摆到你面前，过完还会回访验证。

    ⚠️ 第一版这里是错的：只打开了学习通**首页**。而首页本来就不受限，
    验证码只在访问**课程页 / 作业页**时才弹 —— 结果老大照着做了却什么都没发生。
    现在改成：程序自己把「会触发验证码的那个地址」导航出来，并且过完必须回访确认。
    """
    with browser.open_context(headless=False) as ctx:
        page = browser.first_page(ctx)

        try:
            courses = scanner.fetch_course_list(ctx)
        except scanner.LoginRequired as exc:
            print(f"登录态有问题：{exc}")
            print("先跑「登录学习通.bat」重新登录。")
            return 2
        if not courses:
            print("一个课程都没取到，先跑「登录学习通.bat」。")
            return 2

        probe = scanner._middle_url(courses[0])
        headers = scanner.init_headers(ctx)

        def blocked() -> bool:
            """轻轻碰一下那个地址，看返回的还是不是验证码页。"""
            try:
                resp = ctx.request.get(probe, timeout=config.REQUEST_TIMEOUT_MS, headers=headers)
                return hwparser.looks_like_verify_page(resp.text())
            except Exception:  # noqa: BLE001
                return True

        print("先看看现在是不是还被挡着…", flush=True)
        if not blocked():
            print("→ 没被挡。直接点「开始扫描作业」就行。")
            return 0

        print("=" * 66)
        print("确认还在风控里。验证码页面已经打开在浏览器窗口了：")
        print(">>> 看浏览器，把图片上的 4 位验证码填进去，点「提交」。")
        print("=" * 66, flush=True)
        try:
            page.goto(probe, timeout=config.REQUEST_TIMEOUT_MS, wait_until="domcontentloaded")
            page.bring_to_front()
        except Exception:  # noqa: BLE001
            pass

        for attempt in range(1, 6):
            try:
                input(f"\n[第 {attempt}/5 次] 提交验证码之后，回到这里按回车，我来检查…")
            except (EOFError, KeyboardInterrupt):
                page.wait_for_timeout(180000)
            if not blocked():
                browser.save_login_state(ctx)
                print("✅ 过了！风控已解除，登录态也更新好了。现在去点「开始扫描作业」。")
                return 0
            print("✗ 还是被挡着。可能是输错了，或者又弹了一张新的 —— 去浏览器里再输一次。")
            try:
                page.reload(wait_until="domcontentloaded")
                page.bring_to_front()
            except Exception:  # noqa: BLE001
                pass

        print("\n试了 5 次还是没过。两个建议：")
        print("  1. 先别扫了，过一两个小时再试（风控有时会持续一段时间）；")
        print("  2. 或者只扫少量课程试水：python src/main.py --max-courses 5")
        return 1


def cmd_scan(opts: dict, *, open_dashboard: bool = False) -> int:
    with browser.open_context(headless=opts["headless"]) as ctx:
        try:
            courses = ensure_login(ctx, interactive=not opts["headless"])
            result = do_scan(ctx, courses, opts)
            browser.save_login_state(ctx)  # 服务端可能刷新过 cookie，顺手再存一次
        except scanner.LoginRequired as exc:
            print(f"\n扫描中断：{exc}")
            return 2
    path = finish(result)

    summary = result["summary"]
    print("-" * 58)
    aborted = result.get("aborted_reason")
    if aborted:
        print(f"⚠ 被平台风控中断：{aborted}")
        print(f"  已扫完 {summary['courses_scanned']} 门，结果已保存，没白跑。")
        print("  恢复办法：浏览器打开 i.chaoxing.com 登录并按提示输一次图片验证码，再重新扫描。")
    else:
        print(f"扫描完成：{summary['courses_scanned']} 门课程，作业 {summary['total']} 条")
        print(f"  需要动手 {summary['pending']} 条（未交 {summary['todo']}、待互评 {summary['peer']}）")
    if summary["courses_skipped"]:
        print(f"  已跳过 {summary['courses_skipped']} 门已结课课程")

    if open_dashboard:
        open_in_browser(path, opts)
    return 0


def cmd_dashboard(opts: dict) -> int:
    if not config.DASHBOARD_HTML.exists():
        print("还没有看板数据，先跑一次扫描（扫描作业.bat）。")
        return 1
    open_in_browser(config.DASHBOARD_HTML, opts)
    return 0


def open_in_browser(path: Path, opts: dict) -> None:
    """用系统默认浏览器打开看板 —— 程序立刻退出，窗口留给你自己看。"""
    try:
        os.startfile(str(path))  # noqa: S606  Windows 专属
        print("已在浏览器中打开看板。")
    except Exception as exc:  # noqa: BLE001
        print(f"自动打开失败（{exc}），请手动双击打开：{path}")


def main(argv: list[str]) -> int:
    cmd, opts = _parse_args(argv)
    if opts["headless"]:
        config.HEADLESS_SCAN = True
    config.ensure_dirs()

    handlers = {
        "run": lambda o: cmd_scan(o, open_dashboard=True),
        "scan": lambda o: cmd_scan(o, open_dashboard=False),
        "login": cmd_login,
        "check": cmd_check,
        "dashboard": cmd_dashboard,
        "unblock": cmd_unblock,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print(__doc__)
        return 1
    try:
        with browser.single_instance():
            return handler(opts)
    except KeyboardInterrupt:
        print("\n已中断。")
        return 130
    except RuntimeError as exc:
        # 单实例锁冲突 / 浏览器启动失败：这些 message 本来就是写给人看的，别加类型前缀
        print(f"\n{exc}")
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"出错了：{type(exc).__name__}: {exc}")
        print("排查线索：debug/raw_html/ 下存了原始响应，data/scan_log.txt 是运行日志。")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

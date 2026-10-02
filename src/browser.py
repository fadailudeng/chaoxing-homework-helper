"""Playwright 浏览器封装。

设计要点：
  * 复用本机已安装的 Edge（channel="msedge"），不额外下载 Chromium 内核；
  * 用「持久化用户目录」保存登录态 —— 你手动登录一次，之后直接复用，
    密码全程不经过本程序；
  * 抹掉 navigator.webdriver，降低被风控识别为自动化的概率；
  * 支持传自定义 profile 目录：测试/预览必须用临时目录，
    否则会和正式登录态抢同一个目录导致浏览器起不来。
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from playwright.sync_api import BrowserContext, sync_playwright

import config

try:  # 仅 Windows 有；用于单实例文件锁（进程退出时由系统自动释放，不留死锁）
    import msvcrt
except ImportError:  # pragma: no cover - 非 Windows
    msvcrt = None  # type: ignore[assignment]

# init 脚本：抹掉自动化特征（不少站点的风控会读这两个字段）
_STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'] });
"""

# 用户数据目录被占用时 Chromium/Edge 的典型征兆
_BUSY_SIGNS = ("ProcessSingleton", "SingletonLock", "already in use", "exitCode=21")


def _launch_kwargs(headless: bool, profile_dir: Path) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "user_data_dir": str(profile_dir),
        "headless": headless,
        "viewport": {"width": 1380, "height": 900},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        # 不覆盖 User-Agent：用浏览器自己的最不容易被识别
    }
    if config.BROWSER_CHANNEL:
        kwargs["channel"] = config.BROWSER_CHANNEL
    return kwargs


def _explain(exc: Exception, profile_dir: Path) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if any(sign in text for sign in _BUSY_SIGNS):
        return (
            "浏览器启动失败：用户数据目录被占用了。\n"
            f"      目录：{profile_dir}\n"
            "      常见原因：上一次的浏览器窗口还开着（把它关掉再重跑）；\n"
            "      或者上一次程序异常退出、没来得及清理，等十几秒再试一次。"
        )
    return (
        f"浏览器启动失败：{exc}\n"
        f"      当前用的是 channel={config.BROWSER_CHANNEL!r}。\n"
        "      如果提示找不到浏览器，跑一次：playwright install msedge\n"
        "      （或设环境变量 XXT_BROWSER= 留空，改用默认内核并执行 playwright install chromium）"
    )


@contextmanager
def open_context(
    headless: bool | None = None,
    profile_dir: Path | str | None = None,
) -> Iterator[BrowserContext]:
    """打开一个浏览器上下文。

    profile_dir 决定登录态存在哪儿：
      * 默认 = config.BROWSER_PROFILE_DIR（正式登录态，只在 login/scan 时用）；
      * 测试、预览请显式传一个独立目录，避免和正式登录态互相抢锁。
    """
    config.ensure_dirs()
    if headless is None:
        headless = config.HEADLESS_SCAN

    profile = Path(profile_dir) if profile_dir else config.BROWSER_PROFILE_DIR
    profile.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = None
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                ctx = p.chromium.launch_persistent_context(**_launch_kwargs(headless, profile))
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if any(sign in f"{exc}" for sign in _BUSY_SIGNS) and attempt < 2:
                    time.sleep(2)  # 上一次进程可能还在收尾，稍等重试
                    continue
                raise RuntimeError(_explain(exc, profile)) from exc
        if ctx is None:
            raise RuntimeError(_explain(last_exc or RuntimeError("未知错误"), profile))

        ctx.add_init_script(_STEALTH_JS)
        restore_login_state(ctx)
        try:
            yield ctx
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001
                pass


def first_page(ctx: BrowserContext):
    """拿一个可用的 page（持久化上下文通常会自带一个空白页）。"""
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def preview_profile() -> Path:
    """测试 / 预览专用的独立 profile 目录（不含任何登录态）。"""
    return config.DEBUG_DIR / "preview_profile"


# ── 登录态快照（双保险）──────────────────────────────────
def save_login_state(ctx: BrowserContext) -> bool:
    """把当前登录态快照到 data/login_state.json。

    为什么需要：持久化用户目录里的 cookie 是浏览器**优雅关闭**时才落盘的。
    一旦进程被强杀、或用户直接叉掉控制台窗口，登录态就可能丢失，
    表现出来就是「明明登录过，下次还让我登录」。
    文件里含 cookie，属敏感数据，别外传。
    """
    try:
        state = ctx.storage_state()
        config.STATE_JSON.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:  # noqa: BLE001
        return False


def restore_login_state(ctx: BrowserContext) -> int:
    """启动时把快照里的 cookie 灌回去，返回灌入条数。

    为什么是「覆盖」而**不是**「只补缺的」（2026-09-23 实测教训）：
      浏览器目录里的 cookie 是浏览器**优雅关闭**时才落盘的，程序被强杀就会丢。
      实测出现过：用户目录里只剩 **2 条** chaoxing cookie（残渣），
      而快照里有 **40 条**（完整）。当时为了"避免旧快照覆盖新状态"改成了"只补缺的"，
      结果那 2 条残渣被判定为"已有登录态" → 快照不灌 → 登录态莫名其妙"失效"。
      而快照在所有会改变登录态的时机都会刷新（登录成功 / 过验证码 / 每次扫描结束），
      所以它总是「最新已知良好状态」，直接覆盖是安全的。
    """
    if not config.STATE_JSON.exists():
        return 0
    try:
        state = json.loads(config.STATE_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return 0
    cookies = state.get("cookies") or []
    if not cookies:
        return 0
    try:
        ctx.add_cookies(cookies)
        return len(cookies)
    except Exception:  # noqa: BLE001
        return 0


# ── 单实例锁 ────────────────────────────────────────────
@contextmanager
def single_instance() -> Iterator[None]:
    """同一时刻只允许跑一个实例。

    两个实例抢同一个浏览器用户目录时，第二个会**静默启动失败**（exitCode 21），
    报错信息里还看不出原因。与其让你对着怪错误发呆，不如一开始就拦住。
    """
    config.ensure_dirs()
    handle = open(config.LOCK_FILE, "w")
    locked = False
    try:
        if msvcrt is not None:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as exc:
                handle.close()
                raise RuntimeError(
                    "「学习通作业助手」已经有一个在运行了。\n"
                    "      请先把那个窗口用完或直接关掉，再重新打开本程序。"
                ) from exc
        yield
    finally:
        if locked:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[union-attr]
            except Exception:  # noqa: BLE001
                pass
        try:
            handle.close()
        except Exception:  # noqa: BLE001
            pass

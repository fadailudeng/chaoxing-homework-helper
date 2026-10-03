"""本地界面服务 —— 把「扫描控制 + 作业看板」做成一个网页应用。

为什么不用 tkinter：本机 managed Python 是精简版、不带 tkinter（实测 ModuleNotFoundError）。
改用「标准库 http.server + Edge 应用窗口（--app）」：
  * 零额外依赖（不用装 PySide6 那种上百 MB 的东西）；
  * Edge 的 --app 模式没有地址栏和标签栏，看起来就是个桌面程序；
  * 界面用网页写，比 tkinter 好看得多，也能直接复用看板的渲染逻辑。

服务只监听 127.0.0.1，不对外网开放。
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import browser  # noqa: E402
import cleanup  # noqa: E402
import config  # noqa: E402
import parser as hwparser  # noqa: E402
import report  # noqa: E402
import scanner  # noqa: E402
import tasks  # noqa: E402

MAX_LOG = 300

_lock = threading.Lock()
_state: dict = {
    "running": False,
    "phase": "idle",        # idle / checking / waiting_login / scanning / done / error / aborted
    "message": "准备就绪",
    "log": [],
    "done": 0,
    "total": 0,
    "data": None,
    "courses": None,        # 全部课程列表（选课弹窗用）
    "error": None,
}


# ── 状态维护 ────────────────────────────────────────────
def _log(msg: str, tag: str = "") -> None:
    with _lock:
        _state["log"].append({"t": time.strftime("%H:%M:%S"), "m": msg, "tag": tag})
        if len(_state["log"]) > MAX_LOG:
            _state["log"] = _state["log"][-MAX_LOG:]


def _set(**kwargs) -> None:
    with _lock:
        _state.update(kwargs)


def _load_saved() -> dict | None:
    """启动时先把上次的结果读进来，这样一打开界面就有东西看。"""
    try:
        if config.RESULT_JSON.exists():
            return json.loads(config.RESULT_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None


def snapshot() -> dict:
    with _lock:
        return {
            "running": _state["running"],
            "phase": _state["phase"],
            "message": _state["message"],
            "log": list(_state["log"][-80:]),
            "done": _state["done"],
            "total": _state["total"],
            "data": _state["data"],
            "error": _state["error"],
            # 我加载的是哪一版代码 —— 新的 app.py 靠这个判断要不要把我换掉
            "fingerprint": _FINGERPRINT,
        }


# ── 小工具：读写 json（失败一律吞掉，别让界面因为一个文件坏了就打不开）──
def _read_json(path: Path, default=None):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return default


def _write_json(path: Path, payload) -> None:
    try:
        config.ensure_dirs()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


# ── 课程选择 ────────────────────────────────────────────
def get_selection() -> list[str] | None:
    """用户勾选了哪些课。None ＝ 没选过 ＝ 全扫。"""
    data = _read_json(config.SELECTION_JSON)
    if isinstance(data, dict):
        data = data.get("course_ids")
    if isinstance(data, list):
        return [str(x) for x in data]
    return None


def set_selection(ids: list[str] | None) -> None:
    data = _read_json(config.SELECTION_JSON)
    if not isinstance(data, dict):
        data = {}
    data["course_ids"] = [str(x) for x in (ids or [])]
    _write_json(config.SELECTION_JSON, data)


def get_speed() -> str | None:
    """上次选的速度档位。"""
    data = _read_json(config.SELECTION_JSON)
    if isinstance(data, dict):
        name = data.get("speed")
        if isinstance(name, str) and name in config.SPEED_PRESETS:
            return name
    return None


def set_speed(name: str | None) -> None:
    if name not in config.SPEED_PRESETS:
        return
    data = _read_json(config.SELECTION_JSON)
    if not isinstance(data, dict):
        data = {}
    data["speed"] = name
    _write_json(config.SELECTION_JSON, data)


def speed_options() -> list[dict]:
    """给界面用的档位列表（含每门课平均耗时的粗估，方便算预计时间）。"""
    return [
        {
            "id": key,
            "label": val["label"],
            "desc": val["desc"],
            "sec_per_course": round((val["course"][0] + val["course"][1]) / 2 + 0.4, 2),
        }
        for key, val in config.SPEED_PRESETS.items()
    ]


def _last_stats(course_id: str) -> dict | None:
    """从上次扫描结果里取这门课的作业统计（选课弹窗里显示，方便判断值不值得扫）。"""
    with _lock:
        data = _state.get("data")
    if not data:
        return None
    for course in data.get("courses") or []:
        if str(course.get("course_id")) == str(course_id):
            stats = course.get("stats") or {}
            return {"total": stats.get("total", 0), "pending": stats.get("pending", 0),
                    "error": course.get("error")}
    return None


def get_courses(force: bool = False) -> dict:
    """给选课弹窗用：全部课程 + 上次作业统计 + 已勾选状态。

    优先用缓存（内存 → 磁盘），都没有才临时开一次浏览器去拉（几秒）。
    """
    with _lock:
        cached = _state.get("courses")

    source = "cache"
    if not cached:
        cached = _read_json(config.COURSES_CACHE)
        if cached:
            with _lock:
                _state["courses"] = cached

    if force or not cached:
        try:
            # 只拉一次课程列表（不碰风控敏感的课程页），用无头模式，别弹窗打扰人
            with browser.open_context(headless=True) as ctx:
                cached = scanner.fetch_course_list(ctx)
                browser.save_login_state(ctx)
            scanner._cache_courses(cached)
            with _lock:
                _state["courses"] = cached
            source = "live"
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "courses": [],
                "selected": get_selection(),
                "total": 0,
            }

    return {
        "ok": True,
        "source": source,
        "total": len(cached or []),
        "selected": get_selection(),
        "speed": get_speed(),
        "speeds": speed_options(),
        "courses": [
            {
                "course_id": c.get("course_id"),
                "name": c.get("name"),
                "teacher": c.get("teacher"),
                "last": _last_stats(str(c.get("course_id"))),
            }
            for c in (cached or [])
        ],
    }


# ── 扫描线程 ────────────────────────────────────────────
def _wait_login(ctx, timeout_sec: int = 900) -> list[dict]:
    page = browser.first_page(ctx)
    try:
        page.goto(config.HOME_URL, timeout=config.REQUEST_TIMEOUT_MS, wait_until="domcontentloaded")
        page.bring_to_front()
    except Exception:  # noqa: BLE001
        pass

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        time.sleep(2)
        try:
            courses = scanner.fetch_course_list(ctx)
            if courses:
                return courses
        except scanner.LoginRequired:
            continue
        except Exception:  # noqa: BLE001
            continue
    raise scanner.LoginRequired("等待登录超过了 15 分钟，请重新点「开始扫描」")


def _scan_worker(
    max_courses: int | None = None,
    only_course_ids: list[str] | None = None,
    speed: str | None = None,
) -> None:
    try:
        with browser.single_instance():
            with browser.open_context(headless=False) as ctx:
                _set(phase="checking", message="检查登录状态…")
                _log("正在检查登录状态…")

                courses = None
                try:
                    courses = scanner.fetch_course_list(ctx)
                except scanner.LoginRequired:
                    courses = None

                if not courses:
                    _set(phase="waiting_login", message="请在弹出的浏览器窗口里登录学习通")
                    _log("登录态无效 —— 请在浏览器窗口里登录（登录后自动继续）", "err")
                    courses = _wait_login(ctx)
                    _log("登录成功", "ok")

                browser.save_login_state(ctx)
                _log(f"共 {len(courses)} 门课程，开始逐门抓取…")

                _set(phase="scanning", message="正在逐门抓取作业…", done=0, total=len(courses))

                def on_progress(done, total, name, stats, err):
                    _set(done=done, total=total)
                    if err:
                        _log(f"[{done}/{total}] {name} —— 失败：{err}", "err")
                    else:
                        tag = "warn" if stats.get("pending") else ""
                        _log(f"[{done}/{total}] {name}  作业 {stats['total']} 条，待办 {stats['pending']} 条", tag)

                result = scanner.scan_all(
                    ctx,
                    courses=courses,
                    only_course_ids=only_course_ids,
                    max_courses=max_courses,
                    speed=speed,
                    on_progress=on_progress,
                )
                browser.save_login_state(ctx)

        scanner.save(result)
        report.render(result)

        s = result["summary"]
        aborted = result.get("aborted_reason")
        if aborted:
            message = (
                f"⚠ 被平台风控中断：{aborted}"
                f"（已扫完 {s['courses_scanned']} 门，结果已保存）"
            )
            _set(phase="aborted", message=message, data=result, error=aborted)
            _log(message, "err")
            _log("恢复办法：浏览器打开 i.chaoxing.com 登录并按提示输一次图片验证码，"
                 "然后回来重新点「开始扫描作业」。", "muted")
        else:
            message = (
                f"完成：扫了 {s['courses_scanned']} 门课，作业 {s['total']} 条，"
                f"需要动手 {s['pending']} 条（耗时 {s.get('elapsed_sec', '?')} 秒）"
            )
            _set(phase="done", message=message, data=result, error=None)
            _log(message, "ok")
    except scanner.LoginRequired as exc:
        _set(phase="error", message=f"登录未完成：{exc}", error=str(exc))
        _log(f"登录未完成：{exc}", "err")
    except Exception as exc:  # noqa: BLE001
        _set(phase="error", message=f"出错了：{exc}", error=str(exc))
        _log(f"出错了：{type(exc).__name__}: {exc}", "err")
        _log("排查线索：debug/raw_html/ 是原始响应，data/scan_log.txt 是日志。", "muted")
    finally:
        _set(running=False)


def start_scan(
    max_courses: int | None = None,
    only_course_ids: list[str] | None = None,
    speed: str | None = None,
) -> bool:
    """返回 True 表示这次真的启动了；False 表示已经在跑。

    only_course_ids：只扫勾选的这些课（界面上选课弹窗传进来的）。
    speed：速度档位（gentle / standard / fast）—— 越快风控风险越高。
    """
    with _lock:
        if _state["running"]:
            return False
        _state["running"] = True
        _state["error"] = None
        _state["phase"] = "starting"
        _state["message"] = "正在启动浏览器…"
    threading.Thread(
        target=_scan_worker, args=(max_courses, only_course_ids, speed), daemon=True
    ).start()
    return True


# ── 题目抓取（一键把待办作业的题目抓下来）────────────────
# 与扫描分开一套状态：抓题目和扫作业是两件独立的事，
# 各自能单独跑、单独看进度，互不覆盖。
_tasks_lock = threading.Lock()
_task_state: dict = {
    "running": False,
    "phase": "idle",        # idle / starting / fetching / done / error / aborted
    "message": "准备就绪",
    "log": [],
    "done": 0,
    "total": 0,
    "result": None,
    "error": None,
}


def _tlog(msg: str, tag: str = "") -> None:
    with _tasks_lock:
        _task_state["log"].append({"t": time.strftime("%H:%M:%S"), "m": msg, "tag": tag})
        if len(_task_state["log"]) > MAX_LOG:
            _task_state["log"] = _task_state["log"][-MAX_LOG:]


def _tset(**kwargs) -> None:
    with _tasks_lock:
        _task_state.update(kwargs)


def task_snapshot() -> dict:
    with _tasks_lock:
        return {
            "running": _task_state["running"],
            "phase": _task_state["phase"],
            "message": _task_state["message"],
            "log": list(_task_state["log"][-80:]),
            "done": _task_state["done"],
            "total": _task_state["total"],
            "result": _task_state["result"],
            "error": _task_state["error"],
        }


def task_index() -> dict:
    """题目页要的全部信息：有多少待办、上次抓到什么、速度档位。"""
    homework = _read_json(config.RESULT_JSON)
    return {
        "candidates": tasks.count_candidates(homework),
        "scanned_at": (homework or {}).get("scanned_at"),
        "saved": tasks.load_tasks(),
        "speed": get_speed(),
        "speeds": speed_options(),
    }


def _task_worker(include_expired: bool, max_items: int | None, speed: str | None) -> None:
    try:
        # 用磁盘上的扫描结果，而不是内存里的 _state["data"] ——
        # 这样「先扫描、再抓题」跨进程/跨重启都能接上。
        homework = _read_json(config.RESULT_JSON)
        targets = tasks.collect_targets(
            homework, include_expired=include_expired, max_items=max_items
        )
        if not targets:
            _tset(phase="done", message="没有需要抓的作业（待办是空的）")
            _tlog("没有需要抓的作业 —— 先回主界面扫一次作业", "muted")
            return

        _tset(phase="starting", message="正在启动浏览器…", total=len(targets), done=0)
        _tlog(f"准备抓 {len(targets)} 份作业的题目（含已过期：{'是' if include_expired else '否'}）")

        with browser.single_instance():
            with browser.open_context(headless=False) as ctx:
                _tset(phase="fetching", message="正在逐份抓取题目…")

                def on_progress(done, total, item, stats, err):
                    _tset(done=done, total=total)
                    head = f"[{done}/{total}] {item['course_name']} · {item['title']}"
                    if err:
                        _tlog(f"{head} —— {err}", "err")
                    else:
                        extra = f"，总分 {stats['score']}" if stats.get("score") else ""
                        _tlog(f"{head}  题目 {stats.get('total', 0)} 道{extra}")

                result = tasks.fetch_all(ctx, targets, speed=speed, on_progress=on_progress)
                browser.save_login_state(ctx)

        tasks.save_tasks(result)
        s = result["summary"]
        aborted = result.get("aborted_reason")
        if aborted:
            message = f"⚠ 被平台风控中断：{aborted}（已抓 {s['ok']} 份，结果已保存，没白跑）"
            _tset(phase="aborted", message=message, result=result, error=aborted)
            _tlog(message, "err")
            _tlog("恢复办法：跑「手动过验证码.bat」过一次验证码，再回来重新点抓取。", "muted")
        else:
            message = (f"完成：抓到 {s['ok']} 份作业、共 {s['questions']} 道题"
                       f"（失败 {s['failed']} 份，耗时 {s['elapsed_sec']} 秒）")
            _tset(phase="done", message=message, result=result, error=None)
            _tlog(message, "ok")
    except scanner.LoginRequired as exc:
        _tset(phase="error", message=f"登录未完成：{exc}", error=str(exc))
        _tlog(f"登录未完成：{exc}", "err")
    except Exception as exc:  # noqa: BLE001
        _tset(phase="error", message=f"出错了：{exc}", error=str(exc))
        _tlog(f"出错了：{type(exc).__name__}: {exc}", "err")
    finally:
        _tset(running=False)


def start_task_fetch(
    include_expired: bool = False,
    max_items: int | None = None,
    speed: str | None = None,
) -> bool:
    """返回 True 表示这次真的启动了；False 表示已经在跑。"""
    with _tasks_lock:
        if _task_state["running"]:
            return False
        _task_state.update({
            "running": True, "error": None, "phase": "starting",
            "message": "正在启动浏览器…", "done": 0, "total": 0,
        })
    threading.Thread(
        target=_task_worker, args=(include_expired, max_items, speed), daemon=True
    ).start()
    return True


# ── 手动过验证码（界面版：不用跑去文件夹点 bat）───────────
# 撞风控的时候，原来的做法是让用户去文件夹双击「手动过验证码.bat」。
# 界面里明明能提示、能放按钮，却要人跑一趟，没道理 —— 老大 2026-10-02 提的。
#
# ⚠️ 探测方式刻意**不做网络轮询**：风控期间每隔几秒再发一个请求，等于往枪口上撞。
#    改成读**浏览器当前页面的 DOM**（page.content()）—— 零额外请求。
#    他提交验证码后页面会跳转/刷新，DOM 一变就知道过了。
_unblock_lock = threading.Lock()
_unblock_state: dict = {
    "running": False,
    "phase": "idle",      # idle / checking / waiting / done / error
    "message": "准备就绪",
    "log": [],
    "error": None,
}


def _ulog(msg: str, tag: str = "") -> None:
    with _unblock_lock:
        _unblock_state["log"].append({"t": time.strftime("%H:%M:%S"), "m": msg, "tag": tag})
        if len(_unblock_state["log"]) > MAX_LOG:
            _unblock_state["log"] = _unblock_state["log"][-MAX_LOG:]


def _uset(**kwargs) -> None:
    with _unblock_lock:
        _unblock_state.update(kwargs)


def unblock_snapshot() -> dict:
    with _unblock_lock:
        return {
            "running": _unblock_state["running"],
            "phase": _unblock_state["phase"],
            "message": _unblock_state["message"],
            "log": list(_unblock_state["log"][-40:]),
            "error": _unblock_state["error"],
        }


def _unblock_worker(timeout_sec: int = 300) -> None:
    try:
        with browser.single_instance():
            with browser.open_context(headless=False) as ctx:
                page = browser.first_page(ctx)
                _uset(phase="checking", message="正在检查风控状态…")
                _ulog("正在检查是不是还被挡着…")

                try:
                    courses = scanner.fetch_course_list(ctx)
                except scanner.LoginRequired as exc:
                    _uset(phase="error", message=f"登录态无效：{exc}", error=str(exc))
                    _ulog(f"登录态无效：{exc}", "err")
                    _ulog("回主界面点「开始扫描作业」，按提示重新登录。", "muted")
                    return
                if not courses:
                    _uset(phase="error", message="一门课都没取到，登录态可能已失效")
                    _ulog("一门课都没取到 —— 先重新登录。", "err")
                    return

                probe = scanner._middle_url(courses[0])
                headers = scanner.init_headers(ctx)

                def blocked() -> bool:
                    """只在开始和结束时各探一次，中间绝不轮询。"""
                    try:
                        resp = ctx.request.get(probe, timeout=config.REQUEST_TIMEOUT_MS,
                                               headers=headers)
                        return hwparser.looks_like_verify_page(resp.text())
                    except Exception:  # noqa: BLE001
                        return True

                if not blocked():
                    browser.save_login_state(ctx)
                    _uset(phase="done", message="没被风控挡着 —— 直接回去点「开始扫描作业」就行")
                    _ulog("检查结果：没被挡，可以直接扫描。", "ok")
                    return

                _uset(phase="waiting", message="验证码页面已经打开，请在浏览器窗口里输入并提交…")
                _ulog("确认还在风控里。验证码页面已经打开在浏览器窗口了。", "err")
                _ulog("在那个窗口里输入图片上的 4 位验证码并提交 —— 提交后这里会自动发现，"
                      "不用回来点任何东西。", "muted")
                try:
                    page.goto(probe, timeout=config.REQUEST_TIMEOUT_MS, wait_until="domcontentloaded")
                    page.bring_to_front()
                except Exception:  # noqa: BLE001
                    pass

                deadline = time.time() + timeout_sec
                while time.time() < deadline:
                    time.sleep(2)
                    try:
                        if not hwparser.looks_like_verify_page(page.content()):
                            browser.save_login_state(ctx)
                            _uset(phase="done", message="✅ 过了！风控已解除，登录态也更新了")
                            _ulog("✅ 验证码页面已经跳走 —— 过了！风控已解除。", "ok")
                            _ulog("现在回去点「开始扫描作业」就行。", "ok")
                            return
                    except Exception:  # noqa: BLE001
                        continue

                _uset(phase="error", message=f"等了 {timeout_sec // 60} 分钟还没过，先别扫了",
                      error="timeout")
                _ulog(f"等了 {timeout_sec // 60} 分钟还是验证码页。两个建议：", "err")
                _ulog("1. 先别扫了，过一两个小时再试（风控有时会持续一段时间）；", "muted")
                _ulog("2. 或者用「选择课程」只勾几门，慢慢来。", "muted")
    except RuntimeError as exc:
        # 单实例锁被占（比如正在扫描）—— message 本来就是写给人看的
        _uset(phase="error", message=str(exc), error=str(exc))
        _ulog(str(exc), "err")
    except Exception as exc:  # noqa: BLE001
        _uset(phase="error", message=f"出错了：{exc}", error=str(exc))
        _ulog(f"出错了：{type(exc).__name__}: {exc}", "err")
    finally:
        _uset(running=False)


def start_unblock() -> bool:
    """返回 True 表示这次真的启动了；False 表示已经在跑。"""
    with _unblock_lock:
        if _unblock_state["running"]:
            return False
        _unblock_state.update({"running": True, "phase": "checking",
                               "message": "正在启动浏览器…", "error": None})
    threading.Thread(target=_unblock_worker, daemon=True).start()
    return True


# ── HTTP ────────────────────────────────────────────────
# 404 页面：必须是**能走回去**的页面。界面是 Edge 的 --app 窗口，没有地址栏和后退按钮，
# 纯文本 404 会让人卡在没有出口的页面上（2026-10-02 真踩过），所以这里给链接和关闭按钮。
_NOT_FOUND_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>页面不存在 · 学习通作业助手</title>
<style>
  body{margin:0;background:#eef2f7;color:#1f2328;min-height:100vh;padding:24px;
    display:flex;align-items:center;justify-content:center;
    font:14px/1.7 "Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif}
  .box{background:#fff;border:1px solid #dfe5ec;border-radius:14px;padding:26px 30px;
    max-width:580px;box-shadow:0 12px 34px rgba(15,23,42,.09)}
  h1{margin:0 0 2px;font-size:19px}
  .code{color:#6b7280;font-size:12.5px;margin-bottom:16px;word-break:break-all}
  .why{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;border-radius:9px;
    padding:12px 14px;font-size:13.5px;margin:0 0 16px}
  .why b{color:#9a3412}
  .row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
  a{color:#2f6fbd;text-decoration:none;font-weight:600;font-size:14px}
  a:hover{text-decoration:underline}
  button{font-family:inherit;font-size:13px;border:1px solid #dfe5ec;background:#fff;
    border-radius:8px;padding:7px 15px;cursor:pointer;color:#1f2328}
  button:hover{background:#f6f8fb}
</style>
</head>
<body>
<div class="box">
  <h1>这个地址没有页面</h1>
  <div class="code">404 &nbsp;·&nbsp; __WHAT__</div>
  __HINT__
  <div class="row">
    <a href="/">← 回作业看板</a>
    <button onclick="try{window.close()}catch(e){}">关闭本窗口</button>
  </div>
</div>
</body>
</html>
"""


# ── 「问 AI」快捷入口允许打开的站点 ──────────────────────
# ⚠️ 必须留白名单：这个接口本质是「让服务端替你打开一个网址」，
#    不限制的话就变成了一个任意 URL 打开器（虽然只监听 127.0.0.1，也没必要留这个口子）。
#    网址都在 2026-10-02 实测过：tongyi.com 已 302 到 qianwen.com，所以用新域名。
AI_SITES = {
    "deepseek": {"label": "DeepSeek", "url": "https://chat.deepseek.com/"},
    "qianwen": {"label": "千问", "url": "https://www.qianwen.com/"},
    "glm": {"label": "智谱清言", "url": "https://chatglm.cn/"},
}
_ALLOWED_AI_HOSTS = {
    "chat.deepseek.com",
    "www.qianwen.com", "qianwen.com",
    "chatglm.cn", "www.chatglm.cn",
}


def _die_soon() -> None:
    """稍等片刻再退出进程 —— 给 HTTP 响应留出写回的时间。

    用 os._exit：主线程此刻正卡在 while True: sleep(3600) 里，
    这里只求干脆地让位；该落盘的数据在每次操作结束时就写过了。
    """
    import os  # noqa: PLC0415

    time.sleep(0.5)
    os._exit(0)


class Handler(BaseHTTPRequestHandler):
    server_version = "XXTHelper/1.0"

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _file(self, path: Path, ctype: str) -> None:
        try:
            self._send(200, path.read_bytes(), ctype)
        except OSError:
            self._not_found(str(path))

    def _not_found(self, what: str = "") -> None:
        """找不到页面时给**能走回去**的页面，而不是一行干巴巴的「not found」。

        ⚠️ 为什么值得为 404 写一个页面：界面是 Edge 的 --app 窗口，
        **没有地址栏、没有后退按钮**，只有标题栏一个 X。
        原来 404 返回纯文本，点错一下就成了没有出口的死胡同（2026-10-02 真踩了）。
        """
        safe = str(what).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")[:160]
        hint = ""
        if "/tasks" in str(what):
            hint = (
                '<p class="why"><b>「作业题目」是新增的功能，需要重启界面才能用。</b><br>'
                '当前运行着的界面还是更新前的旧程序：窗口里的网页是每次打开时从磁盘读的'
                '（所以按钮能看到），但服务端路由是程序启动时载入内存的（所以点了会 404）。<br><br>'
                '关掉这个窗口，重新双击桌面的「学习通作业助手」图标就行 —— 不用重新登录。</p>'
            )
        body = _NOT_FOUND_PAGE.replace("__WHAT__", safe).replace("__HINT__", hint)
        self._send(404, body.encode("utf-8"), "text/html; charset=utf-8")

    def _read_body(self) -> dict:
        """读 POST 的 JSON body，任何异常都退化成空 dict（别让界面因为坏请求挂掉）。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:  # noqa: BLE001
            pass
        return {}

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._file(config.UI_HTML, "text/html; charset=utf-8")
        elif path in ("/tasks", "/tasks.html"):
            self._file(config.TASK_PAGE_HTML, "text/html; charset=utf-8")
        elif path == "/api/state":
            self._json(snapshot())
        elif path == "/api/courses":
            # /api/courses?refresh=1 强制重新拉一次（用户怀疑课不全时用）
            self._json(get_courses(force="refresh=1" in self.path))
        elif path == "/api/tasks":
            self._json(task_index())
        elif path == "/api/tasks/state":
            self._json(task_snapshot())
        elif path == "/api/unblock/state":
            self._json(unblock_snapshot())
        elif path == "/api/ai-sites":
            self._json(AI_SITES)
        elif path == "/api/clean/survey":
            # 清理前先看清楚：会删什么、释放多少、哪些是保住的。
            # 界面点「清理缓存」先弹这一份，用户确认了才走 POST /api/clean-cache。
            include_optional = "optional=1" in self.path
            self._json(cleanup.survey(include_optional=include_optional))
        elif path == "/icon.png":
            self._file(config.ASSETS_DIR / "app_icon.png", "image/png")
        elif path == "/icon.ico":
            self._file(config.ASSETS_DIR / "app.ico", "image/x-icon")
        elif path == "/favicon.ico":
            self._file(config.ASSETS_DIR / "app.ico", "image/x-icon")
        else:
            self._not_found(path)

    def do_POST(self) -> None:  # noqa: N802
        route = self.path.split("?", 1)[0]
        if route == "/api/shutdown":
            # 「代码更新了，请让位」—— 由新启动的 app.py 调用。
            # 让旧进程自己退出，比按 PID 杀干净：不用找 PID、不需要任何权限。
            # 先把响应发出去，再退出，否则调用方会看到连接被掐断。
            self._json({"ok": True})
            threading.Thread(target=_die_soon, daemon=True).start()
            return

        if route == "/api/open-url":
            # 「问 AI」按钮用：用系统默认浏览器打开白名单里的 AI 网页。
            # 为什么不让前端直接 window.open：界面跑在 Edge 的 --app 窗口里（没有标签栏），
            # 交给系统浏览器打开体验更正常，也和「点作业名跳学习通」的做法一致。
            payload = self._read_body()
            url = str(payload.get("url") or "").strip()
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in ("http", "https") or host not in _ALLOWED_AI_HOSTS:
                self._json({"ok": False, "error": f"不允许的地址：{host or url[:60]}"})
                return
            try:
                import os  # noqa: PLC0415

                # os.startfile 是 Windows 上"交给默认程序打开"的标准做法 ——
                # main.py 打开静态看板用的就是它，属于本项目已经验证过能用的路径。
                os.startfile(url)  # noqa: S606
                self._json({"ok": True, "url": url, "via": "startfile"})
                return
            except Exception as exc:  # noqa: BLE001
                try:
                    import webbrowser  # noqa: PLC0415

                    if webbrowser.open(url):
                        self._json({"ok": True, "url": url, "via": "webbrowser"})
                        return
                except Exception:  # noqa: BLE001
                    pass
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        if route == "/api/clean-cache":
            # 界面窗口有自己的 Edge profile（data\ui_profile），Edge 会往里下自己的组件，
            # 实测涨到 481 MB（component_crx_cache 184 MB + ProvenanceData 里单个模型 168 MB）。
            #
            # 顺序很讲究 —— 清理范围本身由 src/cleanup.py 的白名单 + 保护清单约束：
            #   1. 先回话（否则窗口一关，前端拿不到响应，只能看到连接被掐断）
            #   2. 关掉我们的 Edge 窗口（profile 被 Edge 占着就删不掉）**和本服务**
            #   3. 删白名单里的东西
            #   4. 重新启动界面
            #
            # 为什么不在本进程里直接删：服务自己的进程不会挡住 data\ui_profile，
            # 但**窗口**会。所以关窗口之后其实可以就地删；不过删除+重开必须
            # 脱离本进程（本进程马上要退出），交给一个分离的 bat 最稳。
            # 好处是 cleanup.py 那套逻辑能单独测，bat 只负责窗口和进程。
            if _state["running"] or _task_state["running"] or _unblock_state["running"]:
                self._json({"ok": False,
                            "error": "有任务正在跑（扫描 / 抓题 / 过验证码），等它结束再清理。"})
                return
            bat = config.ROOT / "清理缓存.bat"
            if not bat.exists():
                self._json({"ok": False, "error": f"找不到 {bat.name}（它应该在程序根目录）"})
                return
            payload = self._read_body()
            include_optional = bool(payload.get("include_optional"))
            try:
                subprocess.Popen(  # noqa: S603
                    ["cmd", "/c", str(bat), "full" if include_optional else "safe"],
                    cwd=str(config.ROOT),
                    creationflags=0x00000008 | 0x00000200,   # DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP
                    close_fds=True,
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._json({"ok": True,
                            "message": "正在清理缓存…界面马上关闭，几秒后会自动重新打开"})
            except Exception as exc:  # noqa: BLE001
                self._json({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            return

        if route == "/api/unblock":
            # 撞风控时点界面上的按钮就走这里 —— 不用去文件夹双击 bat
            self._json({"started": start_unblock()})
            return

        if route == "/api/tasks/fetch":
            payload = self._read_body()

            speed = payload.get("speed")
            if speed not in config.SPEED_PRESETS:
                speed = get_speed()
            else:
                set_speed(speed)

            raw = payload.get("max_items")
            max_items: int | None = None
            if raw not in (None, "", 0, "0"):
                try:
                    max_items = max(1, int(raw))
                except Exception:  # noqa: BLE001
                    max_items = None

            self._json({
                "started": start_task_fetch(
                    include_expired=bool(payload.get("include_expired")),
                    max_items=max_items,
                    speed=speed,
                ),
                "max_items": max_items,
                "speed": speed,
            })
            return

        if route == "/api/scan":
            payload = self._read_body()

            limit: int | None = None
            raw = payload.get("max_courses")
            if raw not in (None, "", 0, "0"):
                try:
                    limit = max(1, int(raw))
                except Exception:  # noqa: BLE001
                    limit = None

            ids = payload.get("course_ids")
            only_ids: list[str] | None = None
            if isinstance(ids, list):
                only_ids = [str(x) for x in ids] or None
                set_selection(only_ids or [])      # 传了就记住，下次打开弹窗还是这套勾选

            speed = payload.get("speed")
            if speed not in config.SPEED_PRESETS:
                speed = get_speed()          # 没传就用上次保存的档位
            else:
                set_speed(speed)

            self._json({
                "started": start_scan(limit, only_ids, speed),
                "max_courses": limit,
                "course_ids": only_ids,
                "speed": speed,
            })
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")  # API：给调用方看的，不用 HTML

    def log_message(self, *args) -> None:  # 别把访问日志刷到控制台
        pass


# ── 启动 ────────────────────────────────────────────────
def open_app_window(url: str) -> bool:
    """用 Edge 的「应用模式」打开界面：没有地址栏和标签栏，就像个桌面程序。"""
    edge = config.find_edge()
    if not edge:
        return False
    try:
        config.WEBVIEW_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(  # noqa: S603
            [
                edge,
                f"--app={url}",
                "--window-size=1020,780",
                f"--user-data-dir={config.WEBVIEW_PROFILE_DIR}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            close_fds=True,
        )
        return True
    except Exception:  # noqa: BLE001
        return False


DEFAULT_PORT = 17321

# ── 代码指纹：判断「正在跑的那个进程是不是已经过期」────────────
# 为什么需要它（2026-10-02 老大提的问题）：
#   界面窗口里的**网页**每次打开都从磁盘读，所以改了 HTML 立刻看得见；
#   但**服务端代码**是进程启动时载入内存的。原来的 serve() 一发现端口上有服务
#   就直接把它调出来复用 —— 于是「关掉窗口再双击图标」永远是旧代码，
#   每次都得手动跑一次「重启界面.bat」。这不是使用者的错，是这里的设计错了。
#
# 现在：app.py 启动时先问旧进程「你加载的代码指纹是多少」，
#   指纹不一样（磁盘上的更新）→ 让旧进程自己退出，用新代码重新起服务。
#   使用者的操作回到直觉：关掉窗口、再双击图标 = 用上新版本。
#
# ⚠️ 指纹**只算 .py**：web/*.html 是每次从磁盘读的，改了不需要重启。
_FINGERPRINT_FILES = (
    "app.py", "server.py", "scanner.py", "parser.py", "task_parser.py",
    "tasks.py", "browser.py", "config.py", "report.py", "main.py",
)


def code_fingerprint() -> str:
    """服务端代码指纹（文件名 + 改动时间 + 大小）。"""
    import hashlib  # noqa: PLC0415

    digest = hashlib.sha1()
    here = Path(__file__).resolve().parent
    for name in _FINGERPRINT_FILES:
        try:
            st = (here / name).stat()
            digest.update(f"{name}:{int(st.st_mtime)}:{st.st_size};".encode())
        except OSError:
            digest.update(f"{name}:missing;".encode())
    return digest.hexdigest()[:16]


# 进程启动时算一次就够了：跑着的时候这些文件不会变，
# 而它必须代表「这个进程实际加载的代码」。
_FINGERPRINT = code_fingerprint()


def _running_info(port: int) -> dict | None:
    """端口上那个服务自我介绍一下；不是我们的服务就返回 None。"""
    import urllib.request  # noqa: PLC0415

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if "phase" in data and "log" in data:
        return data
    return None


def _already_running(port: int) -> bool:
    return _running_info(port) is not None


def _should_take_over(info: dict | None) -> bool:
    """要不要把旧进程换掉。

    换的条件只有一个：**代码指纹不一样**（磁盘上的比它加载的新）。
    ⚠️ 旧进程正在跑任务时不换 —— 抓题/扫描抓一半被踢掉会丢结果，
       提示一下，等它跑完再双击一次就行。
    """
    if not info:
        return False
    if info.get("fingerprint") == _FINGERPRINT:
        return False
    if info.get("running"):
        print("代码有更新，但旧进程正在跑任务 —— 这次先不重启（免得结果丢了）。"
              "等它跑完，再双击一次图标就换成新版。", flush=True)
        return False
    return True


def _kill_pid(pid: str) -> bool:
    """结束一个进程。两种方式都试，**必须看返回码**。

    ⚠️ 教训（2026-10-02 实测）：taskkill 在某些环境下直接报
       `ERROR: Access denied`（返回码 1），而 PowerShell 的 Stop-Process 能成功。
       第一版这里没看 returncode，只要没抛异常就算「杀成功」——
       于是明明没杀掉也返回 True，上层以为端口马上就会让出来。
    """
    attempts = (
        ["taskkill", "/PID", pid, "/F"],
        ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force"],
    )
    for cmd in attempts:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=15, check=False)
            if r.returncode == 0:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _force_stop_pid(port: int) -> bool:
    """兜底：老版本没有 /api/shutdown 接口，只能按端口找 PID 结束它。

    （第一次升级到「自动重启」这一版时会走到这里 —— 那时跑着的旧进程还不认识新接口。）
    """
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=15, check=False).stdout
    except Exception:  # noqa: BLE001
        return False

    pids: set[str] = set()
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                pids.add(parts[-1])

    return any(_kill_pid(pid) for pid in pids)


def _stop_running(port: int) -> bool:
    """让旧进程退出，并等端口让出来。"""
    import urllib.request  # noqa: PLC0415

    clean = False
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/shutdown",
                                     data=b"", method="POST")
        with urllib.request.urlopen(req, timeout=3) as resp:
            clean = bool(json.loads(resp.read().decode("utf-8")).get("ok"))
    except Exception:  # noqa: BLE001
        clean = False

    if not clean:
        print("旧进程不认识「自己退出」的接口（是老版本），改用按端口结束进程…", flush=True)
        if not _force_stop_pid(port):
            print("没能结束旧进程 —— 请手动关掉那个界面窗口，或双击「重启界面.bat」。", flush=True)
            return False

    for _ in range(40):
        time.sleep(0.25)
        if not _already_running(port):
            print("旧进程已退出，正在用新代码启动…", flush=True)
            return True
    print("旧进程退出后端口一直没让出来 —— 稍等几秒再双击一次图标。", flush=True)
    return False


def serve(port: int = DEFAULT_PORT, *, open_window: bool = True, block: bool = True) -> int:
    config.ensure_dirs()
    _set(data=_load_saved())
    # 上次抓好的题目也读进来 —— 打开题目页立刻有东西看，不用重抓
    _tset(result=tasks.load_tasks())

    info = _running_info(port)
    if info is not None:
        if _should_take_over(info):
            if _stop_running(port):
                info = None            # 旧进程走了，往下走正常启动流程
        if info is not None:
            # 代码没变（或任务在跑）→ 复用，只把窗口调出来
            print(f"已经有一个界面在运行了，直接调出来：http://127.0.0.1:{port}/", flush=True)
            if open_window:
                open_app_window(f"http://127.0.0.1:{port}/")
            return port

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)  # 端口被别的程序占了，退到随机端口

    httpd.daemon_threads = True
    actual_port = httpd.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"界面服务已启动：{url}", flush=True)

    if open_window:
        if open_app_window(url):
            print("已用 Edge 应用窗口打开界面。", flush=True)
        else:
            import webbrowser  # noqa: PLC0415

            webbrowser.open(url)
            print("已用默认浏览器打开界面。", flush=True)

    if not block:
        return actual_port

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n界面已关闭。", flush=True)
    return actual_port


if __name__ == "__main__":
    import os  # noqa: PLC0415

    if sys.stdout is not None:
        sys.stdout.reconfigure(encoding="utf-8")
    # XXT_NO_WINDOW=1 只起服务不开窗口（给自己预览 / 自动化测试用）
    _no_window = os.environ.get("XXT_NO_WINDOW") == "1"
    serve(
        int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT,
        open_window=not _no_window,
    )

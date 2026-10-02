"""全局配置：路径、接口地址、限速参数。

原则：业务内容不写死在这里；换环境 / 换浏览器只改本文件或走命令行参数。
限速那几个值是为了避开学习通风控，别随手调大。
"""
from __future__ import annotations

import os
from pathlib import Path

# ── 路径 ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DEBUG_DIR = ROOT / "debug"
WEB_DIR = ROOT / "web"
RAW_HTML_DIR = DEBUG_DIR / "raw_html"

# 登录态就存在这个浏览器用户目录里（含 cookie，属于敏感数据，别外传）
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"
# 登录态双保险：万一浏览器被强杀、profile 没来得及落盘，还能从这份快照恢复
STATE_JSON = DATA_DIR / "login_state.json"
# 单实例锁：两个程序同时抢同一个浏览器目录会让第二个起不来（见 browser.py 注释）
LOCK_FILE = DATA_DIR / "app.lock"
RESULT_JSON = DATA_DIR / "homework.json"
# 全部课程列表的缓存（选课弹窗用，免得每次都开一次浏览器去拉）
COURSES_CACHE = DATA_DIR / "courses_cache.json"
# 用户在选课弹窗里勾选了哪些课
SELECTION_JSON = DATA_DIR / "selection.json"
# 抓下来的作业题目：结构化全量 + 人看的 Markdown
TASKS_JSON = DATA_DIR / "tasks.json"
TASKS_DIR = DATA_DIR / "题目"
DASHBOARD_HTML = WEB_DIR / "作业看板.html"
# 题目页：一键抓取 + 浏览题目（比看板更进一步，能看到「这作业要干什么」）
TASK_PAGE_HTML = WEB_DIR / "题目.html"
SCAN_LOG = DATA_DIR / "scan_log.txt"
ASSETS_DIR = ROOT / "assets"

# ── 接口（学生端，非官方 API）───────────────────────────
HOME_URL = "https://i.chaoxing.com/"
COURSE_LIST_API = "https://mooc1-api.chaoxing.com/mycourse/backclazzdata"
COURSE_MIDDLE_URL = "https://mooc1.chaoxing.com/visit/stucoursemiddle"
WORK_LIST_URL = "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/list"
WORK_TASK_URL = "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task"

# ── 限速（防风控）───────────────────────────────────────
# ⚠️⚠️ 别再把这两个值调小！2026-09-23 的教训：
#   为了「更快」把课程间隔压到 0.2 秒、翻页 0.4 秒，然后全扫 70 门课 ——
#   45 秒内打了 140 个请求，平台直接返回
#   「【9010】操作异常，请输入图片中的验证码」，整轮扫描全废。
#   真人不可能精准地每 0.2 秒点一次；**机械的等间隔节奏本身就是风控特征**。
#   所以这里用「区间」而不是定值：每次请求前在区间内随机取一个等待时长。
# 速度档位：每个档位给 (课程间隔区间, 翻页间隔区间)，请求前在区间内随机取一个值。
# ⚠️ 越快的档位风控风险越高。2026-09-23 我用约 0.25 秒/门（≈3.1 请求/秒）全扫 70 门，
#    直接吃了一张图片验证码。所以即使「快速」档也留了余量（≈1.3 请求/秒），别再往下调。
SPEED_PRESETS = {
    "gentle": {
        "label": "稳妥", "desc": "最不容易被风控，适合很久没扫、或刚被风控过",
        "course": (2.0, 4.0), "page": (1.0, 2.0),
    },
    "standard": {
        "label": "标准", "desc": "默认，速度和安全的折中",
        "course": (1.0, 2.0), "page": (0.6, 1.2),
    },
    "fast": {
        "label": "快速", "desc": "明显更快，但被要求输验证码的风险更高",
        "course": (0.5, 1.0), "page": (0.3, 0.6),
    },
}
SPEED = os.environ.get("XXT_SPEED", "standard")
# 兼容旧引用（等于「标准」档）
COURSE_DELAY_SEC = SPEED_PRESETS["standard"]["course"]
PAGE_DELAY_SEC = SPEED_PRESETS["standard"]["page"]
CONCURRENCY = int(os.environ.get("XXT_CONCURRENCY", "1"))      # 保持串行，别开并发
# 作业列表页**没有分页栏**（实测 #page 元素不存在），所以总页数读不出来。
# 判据改成「这一页满员，就可能还有下一页」—— 满页会多问一页，不满页就停。
# 12 是实测的每页条数；就算平台改版，最坏也只是白问一页，绝不会漏数据。
PAGE_SIZE_GUESS = int(os.environ.get("XXT_PAGE_SIZE", "12"))
MAX_PAGES = 10
REQUEST_TIMEOUT_MS = 15000
RETRY = 2
MAX_COURSES = int(os.environ.get("XXT_MAX_COURSES", "150"))    # 最多扫多少门课（够覆盖全部课程）
# ⚠️ 默认「不跳过」：实测 isretire 字段**不能**用来判断是否已结课（2026-09-23 踩过）。
# 老大 70 门课里 isretire=1 的有 54 门，其中含「2026-2027-1 学期」和一堆本学期专业课；
# 而 isretire=0 的里面反而混着 endDate 早就过去的历史课。照 isretire 过滤会漏掉本学期课程。
# 代价是请求量变大（每门课 2 个请求），所以限速参数必须保持保守。
SKIP_RETIRED = os.environ.get("XXT_SKIP_RETIRED", "0") == "1"

# ── 浏览器 ──────────────────────────────────────────────
# 本机只有 Edge，故默认用 Edge；Playwright 的 msedge 通道复用已安装的 Edge，无需额外下载内核
BROWSER_CHANNEL = os.environ.get("XXT_BROWSER", "msedge")
HEADLESS_SCAN = os.environ.get("XXT_HEADLESS", "0") == "1"   # 默认有头：无头更容易被风控盯上

# ── 界面（本地网页 + Edge 应用窗口）─────────────────────
# managed Python 是精简版、不带 tkinter，所以界面走「标准库 http.server + Edge --app」，
# 零额外依赖，而且窗口没有地址栏，看起来就是个桌面程序。
UI_HTML = WEB_DIR / "ui.html"
WEBVIEW_PROFILE_DIR = DATA_DIR / "ui_profile"     # 界面窗口专用的浏览器目录，不干扰你平时的 Edge
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_edge() -> str | None:
    for path in EDGE_CANDIDATES:
        if Path(path).exists():
            return path
    return None


def speed_preset(name: str | None = None) -> tuple[tuple[float, float], tuple[float, float]]:
    """返回 (课程间隔区间, 翻页间隔区间)，单位秒。"""
    preset = SPEED_PRESETS.get(name or SPEED) or SPEED_PRESETS["standard"]
    return tuple(preset["course"]), tuple(preset["page"])


def ensure_dirs() -> None:
    for d in (DATA_DIR, DEBUG_DIR, WEB_DIR, RAW_HTML_DIR, BROWSER_PROFILE_DIR, ASSETS_DIR):
        d.mkdir(parents=True, exist_ok=True)

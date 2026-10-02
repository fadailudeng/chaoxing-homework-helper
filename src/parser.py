"""学习通「作业列表」HTML 解析。

纯函数、不联网、无副作用 —— 方便配套单测（见 tests/test_parser.py）。

页面结构依据公开的接口逆向结论：
  mooc1.chaoxing.com/mooc-ans/mooc2/work/list 返回 HTML
  作业条目为 <li data="详情页URL">，内含 .overHidden2(标题) / .status(状态) / .time(剩余时间)

已知的坑（按实测记录）：
  1. 状态文本繁简混排（「待互評」/「待互评」），必须正则模糊匹配；
  2. 作业一旦过期，整个 .time 元素会被删掉（不是改 class），此时状态仍写着「未交」；
  3. 已完成的作业本来就没有 .time，所以不能一看到没有 .time 就判过期，要结合状态。
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

# ── 状态归类 ─────────────────────────────────────────────
TODO = "todo"        # 未交
PEER = "peer"        # 待互评
GRADING = "grading"  # 待批阅
DONE = "done"        # 已完成
UNKNOWN = "unknown"  # 认不出来

STATE_TEXT = {
    TODO: "未交",
    PEER: "待互评",
    GRADING: "待批阅",
    DONE: "已完成",
    UNKNOWN: "未知",
}
# 需要用户动手的状态（看板统计「还欠多少」用这个）
PENDING_STATES = (TODO, PEER)
# 顺序要紧：先认「已X」的完成态，否则「待互评」会被后面规则抢走
_STATUS_RULES = (
    (DONE, re.compile(r"已完成|已批改|已批閱|已批阅|已互評|已互评|已提交|已交卷")),
    (PEER, re.compile(r"待互評|待互评")),
    (GRADING, re.compile(r"待批閱|待批阅|待批改|待評分|待评分|待評閱|待评阅")),
    (TODO, re.compile(r"未交|未提交|未完成")),
)

# 剩余时间：「剩余90小时37分钟」「剩余1天2小时」「剩余59分钟」「剩余3天」
_REMAIN_RE = re.compile(r"剩余\s*(?:(\d+)\s*天)?\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分钟)?\s*(?:(\d+)\s*秒)?")
_CLOSED_RE = re.compile(r"已结束|已截止|已过期|已停止")


def classify_status(text: str | None) -> str:
    """把页面上的状态文本归到 5 个类别之一。"""
    t = (text or "").strip()
    if not t:
        return UNKNOWN
    for state, pattern in _STATUS_RULES:
        if pattern.search(t):
            return state
    return UNKNOWN


def parse_remain_hours(text: str | None) -> float | None:
    """「剩余90小时37分钟」→ 90.62（小时），解析不出来返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    if _CLOSED_RE.search(t):
        return 0.0
    m = _REMAIN_RE.search(t)
    if not m or not any(m.groups()):
        return None
    days = int(m.group(1) or 0)
    hours = int(m.group(2) or 0)
    mins = int(m.group(3) or 0)
    secs = int(m.group(4) or 0)
    return round(days * 24 + hours + mins / 60 + secs / 3600, 2)


def _query_param(url: str, key: str) -> str | None:
    m = re.search(rf"[?&]{re.escape(key)}=([0-9]+)", url or "")
    return m.group(1) if m else None


# 平台风控页的特征（要求输图片验证码）
_VERIFY_SIGNS = (
    "请输入图片中的验证码",
    "processVerifyPng",
    "yzmTips",
    "【9010】",
)


def looks_like_verify_page(html: str) -> bool:
    """是不是被平台风控拦下了（要求输图片验证码）。

    这个信号必须**立刻中断整个扫描**，绝不能继续往下撞 ——
    2026-09-23 就是因为没停，把一次可恢复的验证码撞成了 67 门课全军覆没。
    """
    head = (html or "")[:20000]
    return any(sign in head for sign in _VERIFY_SIGNS)


def looks_like_login_page(html: str) -> bool:
    """登录失效时接口会返回登录页 / 空的壳，要能识别出来而不是静默当成「没有作业」。"""
    if not html or len(html) < 200:
        return True
    head = html[:8000]
    if "passport2.chaoxing.com" in head or "passport.chaoxing.com" in head:
        return True
    if re.search(r"请\s*登\s*录|用户登录|账号登录", head):
        return True
    return False


def parse_total_pages(html: str) -> int:
    """从 #page 里取最大页码，取不到就当 1 页。"""
    soup = BeautifulSoup(html or "", "lxml")
    page = soup.select_one("#page")
    if page is None:
        return 1
    pages: list[int] = []
    for li in page.find_all("li"):
        classes = " ".join(li.get("class") or [])
        if "xl-prevPage" in classes or "xl-nextPage" in classes:
            continue
        text = li.get_text(strip=True)
        if text.isdigit():
            pages.append(int(text))
    return max(pages) if pages else 1


def _parse_item(li: Any) -> dict[str, Any] | None:
    title_el = li.select_one(".overHidden2") or li.select_one(".right-content p")
    if title_el is None:  # 没有标题的条目不是作业卡片，跳过
        return None

    title = (title_el.get("title") or title_el.get_text(strip=True) or "").strip()

    status_el = li.select_one(".status")
    status_raw = status_el.get_text(strip=True) if status_el else ""
    state = classify_status(status_raw)

    time_el = li.select_one(".time")
    remain_text = ""
    if time_el is not None:
        # 去掉图标等噪音，只留文字
        remain_text = time_el.get_text(" ", strip=True)

    # 过期判定：有 .time 但 class 里没有 notOver → 已过期；
    # 没 .time 时，只有「还需动手」的状态才算过期（已完成作业本来就没 .time）
    if time_el is None:
        is_expired = state in PENDING_STATES
    else:
        is_expired = "notOver" not in " ".join(time_el.get("class") or [])

    tag_classes: set[str] = set()
    for tag in li.select(".tag"):
        tag_classes.update(tag.get("class") or [])
    label_text = " ".join(el.get_text(strip=True) for el in li.select(".label"))
    is_peer = ("icon-hp-gy" in tag_classes) or ("互评" in label_text) or (state == PEER)

    url = (li.get("data") or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://mooc1.chaoxing.com" + url

    return {
        "title": title,
        "status_raw": status_raw,
        "state": state,
        "state_text": STATE_TEXT[state],
        "is_peer": is_peer,
        "is_expired": bool(is_expired),
        "remain_text": remain_text,
        "remain_hours": parse_remain_hours(remain_text),
        "url": url,
        "work_id": _query_param(url, "workId"),
        "answer_id": _query_param(url, "answerId"),
    }


def parse_homework_list(html: str) -> list[dict[str, Any]]:
    """解析一页作业列表 → 作业条目列表（不含课程信息，由上层拼装）。"""
    soup = BeautifulSoup(html or "", "lxml")
    items: list[dict[str, Any]] = []
    for li in soup.find_all("li"):
        if not li.get("data"):
            continue
        item = _parse_item(li)
        if item is not None:
            items.append(item)
    return items


def summarize(items: list[dict[str, Any]]) -> dict[str, int]:
    """统计各状态数量 + 待办数。"""
    stats = {state: 0 for state in STATE_TEXT}
    for it in items:
        stats[it["state"]] = stats.get(it["state"], 0) + 1
    stats["pending"] = stats[TODO] + stats[PEER]
    stats["total"] = len(items)
    return stats

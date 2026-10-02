"""扫描器：登录态 → 课程列表 → 每门课的作业列表。

⚠️ 关键教训（2026-09-23 实测踩过，别再犯）
--------------------------------------------------
课程中间页 `stucoursemiddle` 会 302 跳到 **mooc2-ans.chaoxing.com**，
而作业列表接口在 **mooc1.chaoxing.com** —— 两个子域不同源，
在页面里 fetch 作业列表会被浏览器同源策略拦掉，报 `TypeError: Failed to fetch`。
（第一版就是这么写的，结果 16 门课**全军覆没**，而课程列表却完全正常，很有迷惑性。）

现在所有数据请求统一走 `ctx.request.get()`（Playwright 的网络层请求）：
  * 不受浏览器同源策略约束；
  * 自动带上上下文的 cookie；
  * **不需要渲染页面**，比 page.goto 快一个数量级。
真实页面导航只保留为「万一拿不到 workEnc」时的兜底。
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from typing import Any

import browser
import config
import parser as hwparser


class LoginRequired(RuntimeError):
    """登录态失效，需要重新登录。"""


class VerificationRequired(RuntimeError):
    """触发了平台风控（要求输图片验证码）。

    遇到这个必须**立刻停**：继续往下请求只会把一次可恢复的验证码
    升级成更重的限制（2026-09-23 就是这么把 67 门课全撞废的）。
    """


# ── 请求头：带上浏览器的 UA + Referer，别让请求看起来像裸脚本 ──
_HEADERS: dict[str, str] = {}


def init_headers(ctx) -> dict[str, str]:
    """从真实浏览器取一次 UA，之后所有请求复用它。"""
    global _HEADERS
    if _HEADERS:
        return _HEADERS
    ua = ""
    try:
        ua = browser.first_page(ctx).evaluate("navigator.userAgent") or ""
    except Exception:  # noqa: BLE001
        pass
    _HEADERS = {
        "Referer": "https://mooc1.chaoxing.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    if ua:
        _HEADERS["User-Agent"] = ua
    return _HEADERS


# ── 落盘原始响应，出问题时用于排查 ───────────────────────
def _dump(name: str, text: str) -> None:
    try:
        config.RAW_HTML_DIR.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w\-.一-鿿]", "_", str(name))[:100]
        (config.RAW_HTML_DIR / f"{safe}.html").write_text(text or "", encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def _log(msg: str) -> None:
    print(msg, flush=True)
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with config.SCAN_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _pause(bounds: tuple[float, float]) -> None:
    """在区间内随机等一会儿再发下一个请求。

    故意不用固定间隔：等间隔的机械节奏本身就是明显的风控特征（2026-09-23 的教训）。
    """
    lo, hi = bounds
    time.sleep(random.uniform(lo, hi))


def _cache_courses(courses: list[dict[str, Any]]) -> None:
    """把完整课程列表缓存下来 —— 界面上的选课弹窗要用，免得每次都开浏览器去拉。"""
    try:
        config.ensure_dirs()
        config.COURSES_CACHE.write_text(
            json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        pass


# ── 1. 课程列表 ──────────────────────────────────────────
def fetch_course_list(ctx) -> list[dict[str, Any]]:
    """拉取所有已加入课程。"""
    url = f"{config.COURSE_LIST_API}?view=json&rss=1"
    resp = ctx.request.get(url, timeout=config.REQUEST_TIMEOUT_MS, headers=init_headers(ctx))
    body = resp.text()
    if resp.status != 200:
        raise LoginRequired(f"课程列表接口返回 HTTP {resp.status}，登录态可能已失效")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        _dump("course_list_raw", body)
        raise LoginRequired("课程列表返回的不是 JSON（多半被重定向到登录页了）") from exc

    if data.get("result") != 1:
        _dump("course_list_raw", body)
        raise LoginRequired(f"课程列表接口应答异常：{data.get('msg') or data.get('result')}")

    courses: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for channel in data.get("channelList") or []:
        content = channel.get("content") or {}
        course_infos = ((content.get("course") or {}).get("data")) or []
        if not course_infos:
            continue
        info = course_infos[0]
        course_id = info.get("id")
        class_id = content.get("id")
        cpi = content.get("cpi")
        if not (course_id and class_id and cpi):
            continue
        # 同一门课会在多个 channel 里重复出现（实测 70 条里有 3 条重复，course_id 完全相同）——
        # 不去重就会把同一门课扫两遍：白花请求，作业数还会翻倍虚高。
        if str(course_id) in seen_ids:
            continue
        seen_ids.add(str(course_id))
        courses.append(
            {
                "course_id": str(course_id),
                "class_id": str(class_id),
                "cpi": str(cpi),
                "name": (info.get("name") or "未命名课程").strip(),
                "teacher": (info.get("teacherfactor") or "").strip(),
                "is_retired": content.get("isretire", 0),
                "end_date": content.get("endDate") or "",
            }
        )
    return courses


# ── 2. 取 workEnc（从 HTML 里抠，不依赖页面渲染）──────────
_ENC_PATTERNS = (
    re.compile(r'id=["\']workEnc["\'][^>]*?value=["\']([0-9a-fA-F]{32})'),
    re.compile(r'value=["\']([0-9a-fA-F]{32})["\'][^>]*?id=["\']workEnc["\']'),
    re.compile(r'workEnc["\']?\s*[:=]\s*["\']([0-9a-fA-F]{32})'),
    re.compile(r'enc["\']?\s*[:=]\s*["\']([0-9a-fA-F]{32})'),
    re.compile(r"enc=([0-9a-fA-F]{32})"),
)


def extract_work_enc(html: str, url: str = "") -> str | None:
    """作业令牌。优先 <input id="workEnc">，其次页面里的 enc 变量 / URL 参数。"""
    text = html or ""
    for pattern in _ENC_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    if url:
        match = re.search(r"[?&]enc=([0-9a-fA-F]{32})", url)
        if match:
            return match.group(1)
    return None


def _middle_url(course: dict[str, Any]) -> str:
    return (
        f"{config.COURSE_MIDDLE_URL}?courseid={course['course_id']}"
        f"&clazzid={course['class_id']}&cpi={course['cpi']}&ismooc2=1&v=2"
    )


def get_work_enc(ctx, page, course: dict[str, Any]) -> tuple[str | None, str]:
    """返回 (enc, 失败原因)。

    主路径＝网络层请求（快）；拿不到再兜底走一次真实页面导航（慢但能吃 JS 渲染）。
    """
    middle = _middle_url(course)
    first_err = ""
    try:
        resp = ctx.request.get(middle, timeout=config.REQUEST_TIMEOUT_MS, headers=init_headers(ctx))
        html = resp.text()
        if hwparser.looks_like_verify_page(html):
            _dump(f"verify_{course['course_id']}", html)   # 留现场，好排查
            raise VerificationRequired("学习通要求输入图片验证码")
        enc = extract_work_enc(html, resp.url)
        if enc:
            return enc, ""
        _dump(f"middle_{course['course_id']}", html)
        first_err = "网络层拿到的页面里没有 workEnc"
    except VerificationRequired:
        raise
    except Exception as exc:  # noqa: BLE001
        first_err = f"网络层请求失败：{exc}"

    # 兜底：真导航一次
    try:
        page.goto(middle, timeout=config.REQUEST_TIMEOUT_MS, wait_until="domcontentloaded")
        enc = extract_work_enc(page.content(), page.url)
        if enc:
            return enc, ""
    except Exception as exc:  # noqa: BLE001
        return None, f"{first_err}；兜底导航也失败：{exc}"

    return None, first_err


# ── 3. 作业列表（同样走网络层）───────────────────────────
def fetch_work_page(ctx, course: dict[str, Any], enc: str, page_num: int) -> str:
    url = (
        f"{config.WORK_LIST_URL}?courseId={course['course_id']}"
        f"&classId={course['class_id']}&cpi={course['cpi']}"
        f"&enc={enc}&pageNum={page_num}"
    )
    resp = ctx.request.get(url, timeout=config.REQUEST_TIMEOUT_MS, headers=init_headers(ctx))
    text = resp.text()
    if hwparser.looks_like_verify_page(text):
        _dump(f"verify_work_{course['course_id']}", text)
        raise VerificationRequired("学习通要求输入图片验证码")
    if hwparser.looks_like_login_page(text):
        raise LoginRequired(f"拉取《{course['name']}》作业列表时被要求登录")
    return text


def _item_key(item: dict[str, Any]) -> str:
    """作业条目的去重键：优先 workId，没有就退回「标题 + 状态」。"""
    wid = item.get("work_id")
    if wid:
        return f"id:{wid}"
    return f"t:{item.get('title')}|{item.get('status_raw')}"


def _has_more(page_items: list[dict[str, Any]], total_pages: int, page_num: int) -> bool:
    """还有没有下一页。

    ⚠️ 作业列表页**没有分页栏**，#page 读不出总页数（实测），所以不能只信 total_pages。
    而接口在页码超范围时**会把第一页原样返回**（不是返回空数组），
    所以也不能靠「这一页非空」判断。
    实际判据：页面自己说了还有 → 有；否则「这一页满员」才继续问下一页。
    """
    if total_pages > page_num:
        return True
    if not page_items:
        return False
    return len(page_items) >= config.PAGE_SIZE_GUESS


def scan_course(
    ctx,
    page,
    course: dict[str, Any],
    page_delay: tuple[float, float] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """扫一门课的全部作业。返回 (作业列表, 错误信息)。"""
    page_delay = page_delay or config.PAGE_DELAY_SEC
    enc, why = get_work_enc(ctx, page, course)
    if not enc:
        return [], why or "没拿到 enc 令牌"

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    page_num = 1
    while page_num <= config.MAX_PAGES:
        last_err: Exception | None = None
        html = ""
        for attempt in range(config.RETRY + 1):
            try:
                html = fetch_work_page(ctx, course, enc, page_num)
                last_err = None
                break
            except (LoginRequired, VerificationRequired):
                raise  # 这两种是「整体性问题」，重试没意义，直接交给上层停
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                _pause((0.8 * (attempt + 1), 1.4 * (attempt + 1)))
        if last_err is not None:
            return items, f"第 {page_num} 页拉取失败：{last_err}"

        if page_num == 1:
            _dump(f"worklist_{course['course_id']}", html)

        page_items = hwparser.parse_homework_list(html)
        fresh = [it for it in page_items if _item_key(it) not in seen]
        seen.update(_item_key(it) for it in page_items)

        # 整页都跟前面重复 → 接口把第一页又返回了一次，说明到头的
        if page_items and not fresh:
            break

        items.extend(fresh)

        if not _has_more(page_items, hwparser.parse_total_pages(html), page_num):
            break
        page_num += 1
        _pause(page_delay)
    return items, None


# ── 编排 ────────────────────────────────────────────────
def scan_all(
    ctx,
    *,
    courses: list[dict[str, Any]] | None = None,
    only_course_ids: list[str] | None = None,
    skip_retired: bool | None = None,
    max_courses: int | None = None,
    speed: str | None = None,
    on_progress=None,
) -> dict[str, Any]:
    """扫课程，返回可直接落盘的汇总结构。

    only_course_ids：只扫这些课程（界面上勾选的结果）。给 None 就是全扫。
    speed：速度档位（gentle / standard / fast），决定请求间隔。
    on_progress(done, total, course_name, stats, err) 供界面显示进度用。
    """
    skip_retired = config.SKIP_RETIRED if skip_retired is None else skip_retired
    max_courses = config.MAX_COURSES if max_courses is None else max_courses
    course_delay, page_delay = config.speed_preset(speed)
    _log(f"速度档位：{speed or config.SPEED}（课程间隔 {course_delay[0]}~{course_delay[1]} 秒）")

    init_headers(ctx)
    page = browser.first_page(ctx)

    courses = courses if courses is not None else fetch_course_list(ctx)
    if not courses:
        raise LoginRequired("没取到任何课程，登录态可能已失效")
    _log(f"共发现 {len(courses)} 门课程")
    _cache_courses(courses)

    if skip_retired:
        # 注意：这个分支默认是关的。isretire 字段实测不可靠（见 config.py 注释），
        # 用它过滤会把本学期课程一起漏掉，只在明确要求时才用。
        scoped = [c for c in courses if str(c["is_retired"]) in ("0", "None")]
        skipped = len(courses) - len(scoped)
        _log(f"按 isretire 标记跳过了 {skipped} 门（该标记不可靠，仅在你主动开启时使用）")
    else:
        scoped = list(courses)
        skipped = 0
    if only_course_ids:
        wanted = {str(x) for x in only_course_ids}
        before = len(scoped)
        scoped = [c for c in scoped if str(c["course_id"]) in wanted]
        _log(f"按勾选的课程过滤：{before} → {len(scoped)} 门")
    scoped = scoped[:max_courses]
    _log(f"本次要扫 {len(scoped)} 门课（共发现 {len(courses)} 门）")

    started = time.time()
    result_courses: list[dict[str, Any]] = []
    aborted: str | None = None
    for idx, course in enumerate(scoped, 1):
        t0 = time.time()
        try:
            items, err = scan_course(ctx, page, course, page_delay=page_delay)
        except VerificationRequired as exc:
            # 撞到风控立刻收手：已经扫到的部分保住，剩下的等风控解除再扫
            aborted = str(exc)
            _log(f"⚠ 被平台风控中断（第 {idx}/{len(scoped)} 门）：{exc}")
            break
        except LoginRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            items, err = [], f"异常：{exc}"

        stats = hwparser.summarize(items)
        course.update({"homeworks": items, "stats": stats, "error": err})
        result_courses.append(course)

        cost = time.time() - t0
        flag = "OK " if not err else "ERR"
        _log(
            f"{flag} [{idx}/{len(scoped)}] {course['name']}"
            f"  作业 {stats['total']} 条，待办 {stats['pending']} 条  ({cost:.1f}s)"
            + (f"  {err}" if err else "")
        )
        if on_progress:
            try:
                on_progress(idx, len(scoped), course["name"], stats, err)
            except Exception:  # noqa: BLE001
                pass
        if idx < len(scoped):
            _pause(course_delay)

    all_items = [hw for c in result_courses for hw in c["homeworks"]]
    overall = hwparser.summarize(all_items)
    overall["courses_total"] = len(courses)
    overall["courses_scanned"] = len(result_courses)
    overall["courses_skipped"] = skipped
    overall["elapsed_sec"] = round(time.time() - started, 1)
    _log(f"扫描耗时 {overall['elapsed_sec']} 秒")

    result: dict[str, Any] = {
        "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "courses": result_courses,
        "summary": overall,
    }
    if aborted:
        result["aborted_reason"] = aborted
        result["aborted_at"] = len(result_courses)
    return result


def save(result: dict[str, Any], *, merge: bool = True) -> None:
    """落盘扫描结果。

    ⚠️ merge=True（默认）很重要：**本次没扫到的课程会保留上次的数据**。
    否则用「只勾有待办的」快速扫一次（十几秒），其他几十门课的记录就全没了 ——
    2026-09-23 就这么丢过一次（只扫 7 门之后，看板上只剩那 7 门）。
    """
    config.ensure_dirs()
    if merge:
        result = _merge_with_previous(result)
    config.RESULT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _log(f"结果已写入 {config.RESULT_JSON}")


def _merge_with_previous(result: dict[str, Any]) -> dict[str, Any]:
    """把本次没扫的课程从上次结果里接过来，并打上 from_cache 标记。"""
    try:
        previous = json.loads(config.RESULT_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return result

    fresh = result.get("courses") or []
    fresh_ids = {str(c.get("course_id")) for c in fresh}
    kept: list[dict[str, Any]] = []
    for course in previous.get("courses") or []:
        if str(course.get("course_id")) in fresh_ids:
            continue
        course = dict(course)
        course["from_cache"] = True
        course["cached_at"] = previous.get("scanned_at")
        kept.append(course)

    if not kept:
        return result

    merged = fresh + kept
    all_items: list[dict[str, Any]] = []
    for course in merged:
        all_items.extend(course.get("homeworks") or [])

    prev_summary = result.get("summary") or {}
    overall = hwparser.summarize(all_items)
    overall["courses_total"] = len(merged)
    overall["courses_scanned"] = len(fresh)
    overall["courses_cached"] = len(kept)
    overall["courses_skipped"] = prev_summary.get("courses_skipped", 0)
    overall["elapsed_sec"] = prev_summary.get("elapsed_sec")

    merged_result = dict(result)
    merged_result["courses"] = merged
    merged_result["summary"] = overall
    _log(f"已合并上次结果：本次扫了 {len(fresh)} 门，沿用上次 {len(kept)} 门")
    return merged_result

"""抓取作业作答页 → 解析 → 落盘（结构化 JSON + 人看的 Markdown）。

⚠️ 功能边界（本项目的底线，改代码别越过去）：
   只做「把你自己的题目抓下来、整理好」。
   **不生成答案、不填写作答框、不提交。** 见 README「风控与边界」。

设计要点：
  * 详情页 URL 里**自带 enc 令牌**（实测 314 条待办全是
    work/task?courseId=&classId=&cpi=&workId=&answerId=&enc=），
    所以抓题目比扫作业列表还少一步 —— 不需要先取 workEnc。
  * 请求走 ctx.request.get()（Playwright 网络层），与 scanner 一致：
    不受同源策略约束、自动带 cookie、不用渲染页面。
  * **复用 scanner 的限速与熔断**：同一个账号、同一套风控特征，
    绝不能因为「抓题目」这条路就绕开限速器（2026-09-23 的教训见 scanner 注释）。
  * 原始 HTML 一律留一份到 debug/raw_html/task_<workId>.html，
    解析不准时能照着原始响应改 parser（这是本项目一贯的排查方式）。
"""
from __future__ import annotations

import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import config
import scanner
import task_parser


# ── 日志 / 落现场：复用 scanner 那一套，保证日志格式与扫描一致 ──
def _log(msg: str) -> None:
    scanner._log(msg)


def _dump(name: str, text: str) -> None:
    scanner._dump(name, text)


def _pause(bounds: tuple[float, float]) -> None:
    """请求之间随机等一会儿（等间隔的机械节奏本身就是风控特征）。"""
    lo, hi = bounds
    time.sleep(random.uniform(lo, hi))


# ── 1. 挑出要抓哪些作业 ──────────────────────────────────
def collect_targets(
    result: dict[str, Any] | None,
    *,
    include_expired: bool = False,
    include_done: bool = False,
    course_ids: list[str] | None = None,
    work_ids: list[str] | None = None,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """从扫描结果里挑出要抓题目的作业。

    默认只挑「还要动手」的（未交 / 待互评）且没过期的 —— 已过期和已完成的
    抓了也没用，白花请求（每次抓取都是一个真实请求，见模块头的风控说明）。
    """
    if not result:
        return []

    wanted_courses = {str(x) for x in course_ids} if course_ids else None
    wanted_works = {str(x) for x in work_ids} if work_ids else None

    targets: list[dict[str, Any]] = []
    seen: set[str] = set()

    for course in result.get("courses") or []:
        cid = str(course.get("course_id") or "")
        if wanted_courses and cid not in wanted_courses:
            continue
        for hw in course.get("homeworks") or []:
            state = hw.get("state")
            # 只抓待办（未交 / 待互评）；除非明确要求，否则不碰已完成
            if state not in ("todo", "peer"):
                if not (include_done and state == "done"):
                    continue
            if hw.get("is_expired") and not include_expired:
                continue
            wid = str(hw.get("work_id") or "")
            if wanted_works and wid not in wanted_works:
                continue
            url = (hw.get("url") or "").strip()
            if not url:
                continue
            if url in seen:          # 同一份作业在多个课程条目里重复出现时别抓两遍
                continue
            seen.add(url)
            targets.append({
                "course_id": cid,
                "course_name": course.get("name") or "未命名课程",
                "from_cache": bool(course.get("from_cache")),
                "work_id": wid,
                "answer_id": str(hw.get("answer_id") or ""),
                "title": hw.get("title") or "(无标题)",
                "state": state,
                "state_text": hw.get("state_text") or "",
                "remain_text": hw.get("remain_text") or "",
                "remain_hours": hw.get("remain_hours"),
                "is_expired": bool(hw.get("is_expired")),
                "url": url,
            })

    # 快的先抓：剩余时间少的排前面（还包括没写剩余时间的）
    targets.sort(key=lambda t: (t["remain_hours"] is None, t["remain_hours"] or 0))
    if max_items:
        targets = targets[:max_items]
    return targets


def count_candidates(result: dict[str, Any] | None) -> dict[str, int]:
    """给界面显示「一共有多少份待办、其中多少已过期」。"""
    if not result:
        return {"pending": 0, "expired": 0, "total": 0}
    pending = expired = 0
    for course in result.get("courses") or []:
        for hw in course.get("homeworks") or []:
            if hw.get("state") in ("todo", "peer"):
                pending += 1
                if hw.get("is_expired"):
                    expired += 1
    return {"pending": pending, "expired": expired, "total": pending}


# ── 2. 抓 + 解析 ─────────────────────────────────────────
def fetch_one(ctx, target: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """抓一份作业的作答页并解析。返回 (解析结果, 错误信息)。"""
    try:
        resp = ctx.request.get(
            target["url"],
            timeout=config.REQUEST_TIMEOUT_MS,
            headers=scanner.init_headers(ctx),
        )
        html = resp.text()
    except Exception as exc:  # noqa: BLE001
        return None, f"请求失败：{exc}"

    # 原始响应一律留现场 —— 解析不准时照着它改 task_parser
    _dump(f"task_{target['work_id'] or 'unknown'}", html)

    # ⚠️ 撞到风控立刻熔断，绝不继续撞下一份（见 scanner 模块头的教训）
    if task_parser.looks_like_verify_page(html):
        raise scanner.VerificationRequired("学习通要求输入图片验证码")
    if task_parser.looks_like_login_page(html):
        raise scanner.LoginRequired(f"抓《{target['title']}》时被要求登录")

    parsed = task_parser.parse_task_page(html)
    if not parsed["ok"]:
        note = "；".join(parsed["warnings"]) or "解析不出题目"
        return parsed, note
    return parsed, None


def fetch_all(
    ctx,
    targets: list[dict[str, Any]],
    *,
    speed: str | None = None,
    on_progress=None,
) -> dict[str, Any]:
    """逐份抓取。返回可直接落盘的结果结构。

    on_progress(done, total, target, stats, err) 供界面显示进度。
    撞到风控会让 VerificationRequired 冒出去 —— 由上层中断，
    但**已经抓到的部分会保住**（跟 scanner 一样，不白跑）。
    """
    course_delay, _page_delay = config.speed_preset(speed)
    _log(f"开始抓题目：{len(targets)} 份，速度档位 {speed or config.SPEED}")

    started = time.time()
    tasks: list[dict[str, Any]] = []
    aborted: str | None = None

    for idx, target in enumerate(targets, 1):
        t0 = time.time()
        try:
            parsed, err = fetch_one(ctx, target)
        except scanner.VerificationRequired as exc:
            aborted = str(exc)
            _log(f"⚠ 抓题目被风控中断（第 {idx}/{len(targets)} 份）：{exc}")
            break
        except scanner.LoginRequired:
            raise
        except Exception as exc:  # noqa: BLE001
            parsed, err = None, f"异常：{exc}"

        stats = (parsed or {}).get("summary") or task_parser.summarize([])
        item = {
            **{k: target[k] for k in (
                "course_id", "course_name", "from_cache", "work_id", "answer_id",
                "title", "state", "state_text", "remain_text", "remain_hours",
                "is_expired", "url",
            )},
            "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "ok": bool(parsed and parsed["ok"]),
            "error": err,
            "page_title": (parsed or {}).get("page_title", ""),
            "questions": (parsed or {}).get("questions", []),
            "summary": stats,
            "fallback_text": (parsed or {}).get("fallback_text", ""),
            "warnings": (parsed or {}).get("warnings", []),
            "cost_sec": round(time.time() - t0, 1),
        }
        tasks.append(item)

        flag = "OK " if item["ok"] else "ERR"
        _log(
            f"{flag} [{idx}/{len(targets)}] {item['course_name']} · {item['title']}"
            f"  题目 {stats.get('total', 0)} 道"
            + (f"  总分 {stats['score']}" if stats.get("score") else "")
            + (f"  {err}" if err else "")
        )
        if on_progress:
            try:
                on_progress(idx, len(targets), item, stats, err)
            except Exception:  # noqa: BLE001
                pass
        if idx < len(targets):
            _pause(course_delay)

    overall = {
        "fetched": len(tasks),
        "ok": sum(1 for t in tasks if t["ok"]),
        "failed": sum(1 for t in tasks if not t["ok"]),
        "questions": sum(t["summary"].get("total", 0) for t in tasks),
        "elapsed_sec": round(time.time() - started, 1),
    }
    _log(f"抓题目结束：{overall['fetched']} 份（成功 {overall['ok']}、失败 {overall['failed']}），"
         f"共 {overall['questions']} 道题，耗时 {overall['elapsed_sec']} 秒")

    result: dict[str, Any] = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tasks": tasks,
        "summary": overall,
    }
    if aborted:
        result["aborted_reason"] = aborted
    return result


# ── 3. 落盘 ──────────────────────────────────────────────
def _safe_name(text: str, limit: int = 60) -> str:
    """文件名消毒：Windows 不允许的字符全换掉，别让一份作业把写盘搞崩。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", str(text or "")).strip(" ._")
    return (cleaned or "未命名")[:limit]


def to_markdown(task: dict[str, Any]) -> str:
    """一份作业渲染成 Markdown（给人看的，离线可读）。"""
    lines: list[str] = []
    lines.append(f"# {task['course_name']} · {task['title']}")
    lines.append("")
    meta = [
        f"- 状态：{task.get('state_text') or task.get('state') or '未知'}",
        f"- 剩余：{task.get('remain_text') or ('已过期' if task.get('is_expired') else '未标注')}",
        f"- 抓取时间：{task.get('fetched_at') or '未知'}",
    ]
    s = task.get("summary") or {}
    if s.get("total"):
        score = f"，总分 {s['score']}" if s.get("score") else ""
        meta.append(f"- 题目：{s['total']} 道{score}")
    if task.get("from_cache"):
        meta.append("- ⚠️ 这条作业来自**上次扫描的旧数据**，截止时间可能已经不准了")
    lines.extend(meta)
    lines.append(f"- 原页面：{task.get('url') or ''}")
    lines.append("")

    if task.get("error"):
        lines.append(f"> ⚠️ {task['error']}")
        lines.append("")

    last_section: str | None = None
    for q in task.get("questions") or []:
        # 按大题分组（「一. 单选题（共20题，20分）」）——30 道题的选择题页没有分组没法看
        section = q.get("section") or ""
        if section and section != last_section:
            lines.append(f"## {section}")
            lines.append("")
            last_section = section
        level = "###" if section else "##"
        sub = "####" if section else "###"

        num = q.get("number") or "?"
        head = f"{level} 第 {num} 题（{q.get('typename') or '未知题型'}"
        head += f"，{q['score']} 分）" if q.get("score") else "）"
        lines.append(head)
        lines.append("")
        if q.get("title"):
            lines.append(f"**{q['title']}**")
            lines.append("")

        # 小节：跳过与标题重复的那一节
        sections = q.get("sections") or {}
        for name, body in sections.items():
            if name == "_intro" or (q.get("title") and name == q["title"]):
                lines.append(body)
                lines.append("")
                continue
            if not body:
                continue
            lines.append(f"{sub} {name}")
            lines.append("")
            lines.append("```" if name.startswith("示例") else "")
            lines.append(body)
            lines.append("```" if name.startswith("示例") else "")
            lines.append("")

        if q.get("options"):
            lines.append(f"{sub} 选项")
            lines.append("")
            for opt in q["options"]:
                lines.append(f"- {opt}")
            lines.append("")

        # 在线判题的代码模板：作答要求常写「只在模板标有【在此补充代码】的位置补代码」，
        # 把模板原样放出来，比只说「在模板里补」有用得多。
        if q.get("code_template"):
            lines.append(f"{sub} 代码模板")
            lines.append("")
            lines.append("```")
            lines.append(q["code_template"])
            lines.append("```")
            lines.append("")

        tags = [f"作答方式：{q.get('answer_kind')}"]
        if q.get("need_upload"):
            tags.append("**要交附件**")
        if q.get("language"):
            tags.append(f"语言编号：{q['language']}")
        lines.append("> " + "　·　".join(tags))
        lines.append("")
        if q.get("warnings"):
            lines.append(f"> ⚠️ 解析警告：{'；'.join(q['warnings'])}")
            lines.append("")

    if not task.get("questions") and task.get("fallback_text"):
        lines.append("## 页面正文（没解析出题目，原样留档）")
        lines.append("")
        lines.append(task["fallback_text"])
        lines.append("")

    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip() + "\n"


def save_tasks(result: dict[str, Any]) -> tuple[Path, list[Path]]:
    """落盘：tasks.json（结构化）+ data/题目/*.md（人看的）。返回 (json 路径, md 路径列表)。"""
    config.ensure_dirs()
    config.TASKS_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    config.TASKS_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for task in result.get("tasks") or []:
        name = f"{_safe_name(task.get('course_name'))}_{_safe_name(task.get('title'))}.md"
        path = config.TASKS_DIR / name
        try:
            path.write_text(to_markdown(task), encoding="utf-8")
            written.append(path)
        except OSError:
            pass

    # 再合成一份「全部题目」，方便一次性翻完 / 直接丢给编辑器里搜
    if written:
        combined = config.TASKS_DIR / "全部题目.md"
        try:
            head = (f"# 全部作业题目\n\n抓取时间：{result.get('fetched_at')}\n"
                    f"共 {result.get('summary', {}).get('ok', 0)} 份、"
                    f"{result.get('summary', {}).get('questions', 0)} 道题\n\n---\n\n")
            body = "\n\n---\n\n".join(to_markdown(t) for t in result.get("tasks") or [] if t.get("ok"))
            combined.write_text(head + body, encoding="utf-8")
            written.append(combined)
        except OSError:
            pass

    _log(f"题目已落盘：{config.TASKS_JSON} 与 {config.TASKS_DIR}（{len(written)} 个文件）")
    return config.TASKS_JSON, written


def load_tasks() -> dict[str, Any] | None:
    """读上次抓好的题目，界面一打开就有东西看。"""
    try:
        if config.TASKS_JSON.exists():
            return json.loads(config.TASKS_JSON.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass
    return None

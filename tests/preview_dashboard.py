"""看板渲染预览：用假数据生成 HTML 并截图，用来肉眼检查界面。

不联网、不需要账号。
跑法：python tests/preview_dashboard.py
产物：debug/preview.html、debug/preview.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import browser  # noqa: E402
import config  # noqa: E402
import report  # noqa: E402


def _hw(title, state, *, remain=None, remain_hours=None, expired=False, peer=False, wid="1"):
    return {
        "title": title,
        "status_raw": state,
        "state": state,
        "state_text": {"todo": "未交", "peer": "待互评", "grading": "待批阅",
                       "done": "已完成", "unknown": "未知"}[state],
        "is_peer": peer,
        "is_expired": expired,
        "remain_text": remain or "",
        "remain_hours": remain_hours,
        "url": "https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=" + wid,
        "work_id": wid,
        "answer_id": None,
    }


SAMPLE = {
    "scanned_at": "2026-09-23 14:52:10",
    "summary": {
        "todo": 3, "peer": 1, "grading": 2, "done": 5, "unknown": 0,
        "pending": 4, "total": 11, "courses_total": 14, "courses_scanned": 4, "courses_skipped": 10,
    },
    "courses": [
        {
            "name": "高等数学 A(2)", "teacher": "张伟", "course_id": "1", "error": None,
            "homeworks": [
                _hw("第八章 多元函数微分学 作业", "todo", remain="剩余5小时20分钟", remain_hours=5.33, wid="101"),
                _hw("第九章 重积分 作业", "todo", remain="剩余2天3小时", remain_hours=51.0, wid="102"),
                _hw("期中测试（补交）", "todo", expired=True, wid="103"),
                _hw("第七章 定积分应用", "done", wid="104"),
            ],
        },
        {
            "name": "大学英语（三）", "teacher": "李娜", "course_id": "2", "error": None,
            "homeworks": [
                _hw("Unit 5 写作任务", "todo", remain="剩余20小时", remain_hours=20.0, wid="201"),
                _hw("Unit 4 课后练习", "done", wid="202"),
                _hw("小组互评：Presentation", "peer", remain="剩余30小时", remain_hours=30.0, peer=True, wid="203"),
            ],
        },
        {
            "name": "数据结构与算法", "teacher": "王强", "course_id": "3", "error": None,
            "homeworks": [
                _hw("实验三 二叉树的遍历", "grading", wid="301"),
                _hw("实验二 链表实现", "grading", wid="302"),
                _hw("实验一 顺序表", "done", wid="303"),
            ],
        },
        {
            "name": "马克思主义基本原理", "teacher": "陈静", "course_id": "4",
            "error": "没拿到 enc 令牌",
            "homeworks": [],
        },
    ],
}


def main() -> int:
    config.ensure_dirs()
    out = config.DEBUG_DIR / "preview.html"
    report.render(SAMPLE, out)
    print(f"HTML 已生成：{out}", flush=True)

    shot = config.DEBUG_DIR / "preview.png"
    # 用独立的 profile：绝不能占用正式登录态目录，否则会和扫描抢锁
    with browser.open_context(headless=True, profile_dir=browser.preview_profile()) as ctx:
        page = browser.first_page(ctx)
        page.set_viewport_size({"width": 1120, "height": 1500})
        page.goto(out.as_uri())
        page.wait_for_timeout(500)
        # 展开全部课程后截图，保证所有行都可见
        page.evaluate("document.querySelectorAll('.course').forEach(function(e){e.classList.add('open')})")
        page.wait_for_timeout(200)
        page.screenshot(path=str(shot), full_page=True)
    print(f"截图已生成：{shot}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""诊断：把「课程列表」接口的原始结构摊开看（需要已登录）。

跑法：python tests/inspect_courses.py

用途：
  1. 确认「跳过已结课」这个判断有没有误伤到本学期的课；
  2. 看一个 channel 里是不是挂了多门课（如果只取第一门就会漏课）；
  3. 原始 JSON 落盘到 debug/course_list_raw.json，以后改判定逻辑有据可依。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import browser  # noqa: E402
import config  # noqa: E402
import scanner  # noqa: E402


def main() -> int:
    config.ensure_dirs()
    with browser.open_context(headless=True) as ctx:
        scanner.init_headers(ctx)
        url = f"{config.COURSE_LIST_API}?view=json&rss=1"
        resp = ctx.request.get(url, timeout=config.REQUEST_TIMEOUT_MS, headers=scanner._HEADERS)
        data = json.loads(resp.text())

        if data.get("result") != 1:
            print(f"接口没返回正常数据：{data.get('msg')}")
            print("（多半是登录态过期，先跑一次 登录学习通.bat）")
            return 2

        raw = config.DEBUG_DIR / "course_list_raw.json"
        raw.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        channels = data.get("channelList") or []
        print(f"channelList 共 {len(channels)} 项   原始 JSON 已存：{raw}\n")

        retire_dist: Counter = Counter()
        multi: list[str] = []
        rows: list[tuple] = []

        for ch in channels:
            content = ch.get("content") or {}
            infos = ((content.get("course") or {}).get("data")) or []
            retire = content.get("isretire")
            retire_dist[str(retire)] += 1
            if len(infos) > 1:
                multi.append(str([i.get("name") for i in infos]))
            names = [str(i.get("name")) for i in infos] or ["(无课程名)"]
            rows.append((retire, content.get("id"), content.get("cpi"), content.get("endDate"), names))

        print(f"isretire 取值分布：{dict(retire_dist)}")
        print(f"一个 channel 里挂多门课的：{len(multi)} 个" + (f"  {multi[:3]}" if multi else ""))
        print()
        print("标记说明：  [扫]=会被扫描   [跳]=被「已结课」规则跳过")
        print("-" * 78)
        for retire, class_id, cpi, end, names in rows:
            mark = "扫" if str(retire) in ("0", "None") else "跳"
            print(f"[{mark}] isretire={str(retire):>5}  end={str(end or '-'):<17} {names[0]}")
            for extra in names[1:]:
                print(f"                                    └─（同 channel 第 2 门）{extra}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

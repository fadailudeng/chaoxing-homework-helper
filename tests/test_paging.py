"""分页与去重逻辑单测（不需要联网、不用账号）。

背景（2026-09-23 的坑）：
  作业列表页**没有分页栏**（#page 元素不存在），总页数读不出来；
  而接口在页码超范围时**会把第一页原样返回**（不是返回空数组）。
  所以「还有没有下一页」和「哪些是新条目」都得靠自己的判据 ——
  之前只信 #page，结果所有作业超过 12 条的课都漏了第二页。

跑法：python tests/test_paging.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import config  # noqa: E402
import scanner  # noqa: E402

FULL = config.PAGE_SIZE_GUESS


def item(wid, title="作业"):
    return {"work_id": wid, "title": title, "status_raw": "未交"}


class TestHasMore(unittest.TestCase):
    def test_full_page_continues(self):
        """满页 → 可能还有下一页，要再问一次。"""
        self.assertTrue(scanner._has_more([item(str(i)) for i in range(FULL)], 1, 1))

    def test_partial_page_stops(self):
        """不满页 → 肯定到头了。"""
        self.assertFalse(scanner._has_more([item(str(i)) for i in range(3)], 1, 1))

    def test_empty_page_stops(self):
        self.assertFalse(scanner._has_more([], 1, 1))

    def test_page_counter_wins_when_present(self):
        """页面万一真给了分页栏，就听它的（哪怕这页不满）。"""
        self.assertTrue(scanner._has_more([item("1")], 3, 1))

    def test_full_page_on_last_page_asks_once_more(self):
        """满页时即使已是最后一页也会多问一次 —— 靠去重兜底，不会漏也不会重复。"""
        self.assertTrue(scanner._has_more([item(str(i)) for i in range(FULL)], 2, 2))


class TestItemKey(unittest.TestCase):
    def test_work_id_preferred(self):
        self.assertEqual(scanner._item_key(item("123")), "id:123")

    def test_fallback_to_title_and_status(self):
        self.assertEqual(
            scanner._item_key({"title": "第一章", "status_raw": "未交"}), "t:第一章|未交"
        )


class TestDedupBehaviour(unittest.TestCase):
    """模拟 scan_course 里的去重判断：整页重复 ＝ 到头。"""

    def test_repeated_page_means_stop(self):
        seen = {"id:1", "id:2"}
        page = [item("1"), item("2")]          # 接口把第一页又返回了一遍
        fresh = [it for it in page if scanner._item_key(it) not in seen]
        self.assertEqual(fresh, [], "整页重复应当被识别为『没有更多页』")

    def test_new_page_means_continue(self):
        seen = {"id:1", "id:2"}
        page = [item("3")]                     # 新条目
        fresh = [it for it in page if scanner._item_key(it) not in seen]
        self.assertEqual(len(fresh), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

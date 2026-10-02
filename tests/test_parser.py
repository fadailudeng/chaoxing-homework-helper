"""parser.py 单测：用构造样本覆盖真实页面里出现过的全部坑。

跑法：python tests/test_parser.py
（不联网、不需要学习通账号，可随时回归）
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import parser as P  # noqa: E402

# ── 样本：一条「未交且有剩余时间」的作业 ─────────────────
ITEM_TODO = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?courseId=111&classId=222&cpi=333&workId=4444&answerId=5555&enc=abc123">
  <div class="tag icon-zy"></div>
  <div class="right-content">
    <p class="overHidden2 fl">第一章 绪论</p>
    <p class="status fl">未交</p>
  </div>
  <div class="time notOver" tabindex="0">
    <img src="//mooc1.chaoxing.com/mooc-ans/mooc2/images/endTime.png">剩余90小时37分钟
  </div>
  <div class="clearfix"></div>
</li>
"""

# 已过期：.time 被整个删掉，状态仍是「未交」
ITEM_EXPIRED = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=6666">
  <div class="tag icon-zy"></div>
  <div class="right-content">
    <p class="overHidden2 fl">第二章 习题</p>
    <p class="status fl">未交</p>
  </div>
  <div class="clearfix"></div>
</li>
"""

# .time 还在但 class 丢了 notOver → 也是过期
ITEM_TIME_NO_NOTOVER = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=7777">
  <div class="tag icon-zy"></div>
  <div class="right-content">
    <p class="overHidden2 fl">第三章 小测</p>
    <p class="status fl">未交</p>
  </div>
  <div class="time" tabindex="0">剩余0分钟</div>
</li>
"""

ITEM_PEER = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=8888">
  <div class="tag icon-hp-gy"></div>
  <div class="right-content">
    <p class="overHidden2 fl">互评作业：课程设计</p>
    <p class="status fl">待互評</p>
    <i class="label fl">互评</i>
  </div>
  <div class="time notOver" tabindex="0">剩余12小时5分钟</div>
</li>
"""

ITEM_GRADING = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=9999">
  <div class="tag icon-zy-g"></div>
  <div class="right-content">
    <p class="overHidden2 fl">第四章 作业</p>
    <p class="status fl">待批閱</p>
  </div>
</li>
"""

ITEM_DONE = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=1010">
  <div class="tag icon-zy-g"></div>
  <div class="right-content">
    <p class="overHidden2 fl">已完成的作业</p>
    <p class="status fl">已完成</p>
  </div>
</li>
"""

ITEM_PEER_DONE = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=1111">
  <div class="tag icon-hp-gy"></div>
  <div class="right-content">
    <p class="overHidden2 fl">已互评的作业</p>
    <p class="status fl">已互评</p>
    <i class="label fl">互评</i>
  </div>
</li>
"""

# 状态文本对不上任何规则
ITEM_WEIRD = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=1212">
  <div class="right-content">
    <p class="overHidden2 fl">状态异常的作业</p>
    <p class="status fl">某某某</p>
  </div>
</li>
"""

ITEM_NO_TITLE = """
<li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=1313">
  <div class="clearfix"></div>
</li>
"""

LI_WITHOUT_DATA = """
<li>
  <div class="right-content"><p class="overHidden2 fl">不该被解析的条目</p></div>
</li>
"""


def wrap(*items: str) -> str:
    return "<html><body><ul class='work-list'>" + "".join(items) + "</ul></body></html>"


class TestStatus(unittest.TestCase):
    def test_todo(self):
        items = P.parse_homework_list(wrap(ITEM_TODO))
        self.assertEqual(len(items), 1)
        it = items[0]
        self.assertEqual(it["state"], P.TODO)
        self.assertEqual(it["state_text"], "未交")
        self.assertFalse(it["is_expired"])
        self.assertFalse(it["is_peer"])
        self.assertEqual(it["remain_text"], "剩余90小时37分钟")
        self.assertEqual(it["remain_hours"], 90.62)
        self.assertEqual(it["work_id"], "4444")
        self.assertEqual(it["answer_id"], "5555")

    def test_expired_when_time_removed(self):
        it = P.parse_homework_list(wrap(ITEM_EXPIRED))[0]
        self.assertEqual(it["state"], P.TODO)
        self.assertTrue(it["is_expired"], "无 .time 的未交作业应判为已过期")
        self.assertIsNone(it["remain_hours"])

    def test_expired_when_notover_class_missing(self):
        it = P.parse_homework_list(wrap(ITEM_TIME_NO_NOTOVER))[0]
        self.assertTrue(it["is_expired"])

    def test_peer_review(self):
        it = P.parse_homework_list(wrap(ITEM_PEER))[0]
        self.assertEqual(it["state"], P.PEER)
        self.assertTrue(it["is_peer"])
        self.assertFalse(it["is_expired"])
        self.assertEqual(it["remain_hours"], 12.08)

    def test_grading_traditional(self):
        it = P.parse_homework_list(wrap(ITEM_GRADING))[0]
        self.assertEqual(it["state"], P.GRADING)
        self.assertIsNone(it["remain_hours"])

    def test_done(self):
        it = P.parse_homework_list(wrap(ITEM_DONE))[0]
        self.assertEqual(it["state"], P.DONE)
        self.assertFalse(it["is_expired"], "已完成作业没有 .time，不该被判过期")

    def test_peer_done_counts_as_done_and_peer(self):
        it = P.parse_homework_list(wrap(ITEM_PEER_DONE))[0]
        self.assertEqual(it["state"], P.DONE)
        self.assertTrue(it["is_peer"])

    def test_unknown_state(self):
        it = P.parse_homework_list(wrap(ITEM_WEIRD))[0]
        self.assertEqual(it["state"], P.UNKNOWN)

    def test_classify_status_directly(self):
        self.assertEqual(P.classify_status("未提交"), P.TODO)
        self.assertEqual(P.classify_status("待批改"), P.GRADING)
        self.assertEqual(P.classify_status("已互評"), P.DONE)
        self.assertEqual(P.classify_status(""), P.UNKNOWN)
        self.assertEqual(P.classify_status(None), P.UNKNOWN)

    def test_remain_hours_formats(self):
        self.assertEqual(P.parse_remain_hours("剩余1天2小时"), 26.0)
        self.assertEqual(P.parse_remain_hours("剩余59分钟"), 0.98)
        self.assertEqual(P.parse_remain_hours("剩余3天"), 72.0)
        self.assertEqual(P.parse_remain_hours("已结束"), 0.0)
        self.assertIsNone(P.parse_remain_hours("没有剩余时间"))
        self.assertIsNone(P.parse_remain_hours(""))


class TestRobustness(unittest.TestCase):
    def test_skip_li_without_title(self):
        self.assertEqual(P.parse_homework_list(wrap(ITEM_NO_TITLE)), [])

    def test_skip_li_without_data(self):
        self.assertEqual(P.parse_homework_list(wrap(LI_WITHOUT_DATA)), [])

    def test_title_attribute_wins(self):
        html = """
        <li data="https://mooc1.chaoxing.com/x?workId=1">
          <div class="right-content">
            <p class="overHidden2 fl" title="完整标题很长很长">完整标题很...</p>
            <p class="status fl">未交</p>
          </div>
        </li>"""
        self.assertEqual(P.parse_homework_list(html)[0]["title"], "完整标题很长很长")

    def test_relative_url_normalized(self):
        html = """
        <li data="//mooc1.chaoxing.com/x?workId=1">
          <div class="right-content"><p class="overHidden2 fl">A</p><p class="status fl">未交</p></div>
        </li>"""
        self.assertTrue(P.parse_homework_list(html)[0]["url"].startswith("https://"))

    def test_mixed_page(self):
        html = wrap(ITEM_TODO, ITEM_EXPIRED, ITEM_PEER, ITEM_GRADING, ITEM_DONE, ITEM_PEER_DONE, ITEM_WEIRD)
        items = P.parse_homework_list(html)
        self.assertEqual(len(items), 7)
        stats = P.summarize(items)
        self.assertEqual(stats[P.TODO], 2)
        self.assertEqual(stats[P.PEER], 1)
        self.assertEqual(stats[P.GRADING], 1)
        self.assertEqual(stats[P.DONE], 2)
        self.assertEqual(stats[P.UNKNOWN], 1)
        self.assertEqual(stats["pending"], 3)
        self.assertEqual(stats["total"], 7)

    def test_empty_html(self):
        self.assertEqual(P.parse_homework_list(""), [])


class TestPagination(unittest.TestCase):
    def test_multi_page(self):
        html = """
        <div id="page">
          <li class="xl-prevPage">上一页</li>
          <li class="xl-active">1</li>
          <li>2</li>
          <li>3</li>
          <li class="xl-nextPage">下一页</li>
        </div>"""
        self.assertEqual(P.parse_total_pages(html), 3)

    def test_no_page_element(self):
        self.assertEqual(P.parse_total_pages("<html></html>"), 1)


class TestLoginDetection(unittest.TestCase):
    def test_login_page_detected(self):
        html = "<html><head><meta http-equiv='refresh' content='0;url=https://passport2.chaoxing.com/login'></head></html>"
        self.assertTrue(P.looks_like_login_page(html))

    def test_chinese_login_form(self):
        self.assertTrue(P.looks_like_login_page("<html><body><h1>用户登录</h1>" + "x" * 500 + "</body></html>"))

    def test_tiny_body_is_treated_as_failure(self):
        self.assertTrue(P.looks_like_login_page("<html></html>"))

    def test_normal_page_passes(self):
        self.assertFalse(P.looks_like_login_page(wrap(ITEM_TODO)))


class TestVerifyPageDetection(unittest.TestCase):
    """风控页识别。

    这条必须准：认不出来就会一直往下撞请求，
    把一次可恢复的图片验证码撞成整轮扫描全废（2026-09-23 的真实教训）。
    """

    def test_real_verify_page(self) -> None:
        # 结构抄自学习通真实返回（debug/raw_html/middle_*.html）
        html = (
            "<!doctype html><html><head><title>提示页面</title>"
            "<style>.yzmTips{margin:20px}</style></head><body>"
            '<div class="yzmTips"><p>【9010】操作异常，请输入图片中的验证码</p>'
            '<img src="/processVerifyPng.ac?t=123" width="104" height="44"></div>'
            "</body></html>"
        )
        self.assertTrue(P.looks_like_verify_page(html))

    def test_normal_worklist_is_not_verify_page(self) -> None:
        html = (
            '<ul><li data="https://mooc1.chaoxing.com/mooc-ans/mooc2/work/task?workId=1">'
            '<div class="right-content"><p class="overHidden2 fl">第一章 作业</p>'
            '<p class="status fl">未交</p></div></li></ul>'
        )
        self.assertFalse(P.looks_like_verify_page(html))

    def test_empty_html_is_not_verify_page(self) -> None:
        self.assertFalse(P.looks_like_verify_page(""))


if __name__ == "__main__":
    unittest.main(verbosity=2)

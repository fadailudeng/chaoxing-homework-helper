"""打包给 AI 的测试（不联网）。

守两件事：
  1. **内容完整** —— 题干、选项、输入/输出格式、示例、代码模板都要在，
     少一样 AI 就拿不到完整信息，答出来的东西没法用。
  2. **边界不越** —— 产出的是「题目 + 一句作答要求」，**不含任何答案**。
     这条是项目的底线（README「风控与边界」），用测试钉住。

跑法：python tests/test_pack.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pack  # noqa: E402


def fake_task(**kw) -> dict:
    base = {
        "course_name": "数据分析与可视化",
        "title": "第3次作业",
        "state_text": "未交",
        "remain_text": "剩余 10 小时",
        "url": "https://example.invalid/task?id=1",
        "questions": [],
    }
    base.update(kw)
    return base


def fake_q(**kw) -> dict:
    base = {
        "number": 1,
        "typename": "程序题",
        "score": 25.0,
        "section": "",
        "title": "统计游客总量",
        "sections": {
            "_intro": "某景区连续 n 天的游客量，每行一个数字。",
            "输入格式": "第一行 n，接下来 n 行每行一个整数。",
            "输出格式": "输出总量。",
            "示例输入": "3\n10\n20\n30",
            "示例输出": "60",
        },
        "options": [],
        "code_template": "def get_total(values):\n    # 【在此补充代码】\n    pass",
    }
    base.update(kw)
    return base


class TestContent(unittest.TestCase):
    """内容必须完整。"""

    def test_all_parts_present(self):
        text = pack.build_pack([fake_task(questions=[fake_q()])])
        for needle, why in (
            ("统计游客总量", "题干"),
            ("输入格式", "输入格式"),
            ("输出格式", "输出格式"),
            ("示例输入", "示例输入"),
            ("示例输出", "示例输出"),
            ("def get_total", "代码模板"),
            ("程序题", "题型"),
            ("25.0", "分值"),
        ):
            with self.subTest(part=why):
                self.assertIn(needle, text, f"{why} 丢了")

    def test_example_wrapped_in_code_fence(self):
        """示例要包在代码块里，否则 AI 看不清哪些是输入哪些是说明。"""
        text = pack.build_pack([fake_task(questions=[fake_q()])])
        idx = text.index("示例输入")
        after = text[idx:idx + 80]
        self.assertIn("```", after, "示例没有被代码块包住")
        self.assertIn("10", after)

    def test_options_included(self):
        q = fake_q(number=2, typename="单选题",
                   title="以下哪个正确？", options=["A. 甲", "B. 乙", "C. 丙"],
                   sections={"_intro": "选一个。"}, code_template="")
        text = pack.build_pack([fake_task(questions=[q])])
        for opt in ("A. 甲", "B. 乙", "C. 丙"):
            self.assertIn(opt, text)

    def test_multiple_tasks_separated(self):
        a = fake_task(title="作业A", questions=[fake_q()])
        b = fake_task(title="作业B", questions=[fake_q(number=1)])
        text = pack.build_pack([a, b])
        self.assertIn("作业A", text)
        self.assertIn("作业B", text)
        self.assertIn("---", text)

    def test_sections_ordered(self):
        """大题分组要保留（30 道选择题不分组没法看）。"""
        qs = [fake_q(number=1, section="一. 单选题（共2题）"),
              fake_q(number=2, section="一. 单选题（共2题）"),
              fake_q(number=3, section="二. 程序题（共1题）")]
        text = pack.build_pack([fake_task(questions=qs)])
        self.assertIn("一. 单选题", text)
        self.assertIn("二. 程序题", text)
        # 分组标题只出现一次，不该每道题都重复
        self.assertEqual(text.count("## 一. 单选题（共2题）"), 1)


class TestBoundary(unittest.TestCase):
    """底线：只整理题目，不产答案。"""

    def test_has_instruction(self):
        text = pack.build_pack([fake_task(questions=[fake_q()])])
        self.assertIn("请帮我完成下面这些作业题", text)
        self.assertIn("每道题给出答案", text)

    def test_instruction_can_be_omitted(self):
        text = pack.build_pack([fake_task(questions=[fake_q()])],
                               include_instruction=False)
        self.assertNotIn("请帮我完成下面这些作业题", text)

    def test_no_answer_generated(self):
        """产出里不能出现任何"我们自己给的答案"。

        题目数据里本来就没有答案字段，这条测的是**没有偷偷加进去**。
        """
        text = pack.build_pack([fake_task(questions=[fake_q()])])
        for forbidden in ("参考答案", "正确答案是", "答案：", "答案为"):
            with self.subTest(word=forbidden):
                self.assertNotIn(forbidden, text)

    def test_url_hidden_by_default(self):
        """URL 对 AI 没用，默认不写进去（少一行噪声）。"""
        text = pack.build_pack([fake_task(questions=[fake_q()])])
        self.assertNotIn("example.invalid", text)

    def test_url_can_be_included(self):
        text = pack.build_pack([fake_task(questions=[fake_q()])], include_url=True)
        self.assertIn("example.invalid", text)


class TestFilename(unittest.TestCase):
    def test_single_task(self):
        name = pack.suggest_filename([fake_task()])
        self.assertTrue(name.endswith(".md"))
        self.assertIn("数据分析与可视化", name)

    def test_illegal_chars_cleaned(self):
        bad = fake_task(title='第3次: CS/?*"<>|作业')
        name = pack.suggest_filename([bad])
        for ch in '\\/:*?"<>|':
            self.assertNotIn(ch, name.replace(".md", ""))

    def test_multi_same_course(self):
        name = pack.suggest_filename([fake_task(), fake_task()])
        self.assertIn("共2份", name)

    def test_multi_different_course(self):
        name = pack.suggest_filename([fake_task(), fake_task(course_name="软件工程")])
        self.assertIn("全部待办", name)

    def test_empty(self):
        self.assertTrue(pack.suggest_filename([]).endswith(".md"))

    def test_length_capped(self):
        long = fake_task(title="很长的标题" * 40)
        name = pack.suggest_filename([long])
        self.assertLessEqual(len(name), 84)


class TestRealDataShape(unittest.TestCase):
    """拿真实的 data/tasks.json（如果存在）跑一遍，确认不出错、内容非空。"""

    def test_real_file(self):
        import json

        path = ROOT / "data" / "tasks.json"
        if not path.exists():
            self.skipTest("没有 data/tasks.json（还没抓过题目）")
        data = json.loads(path.read_text(encoding="utf-8"))
        all_tasks = data.get("tasks") or []
        if not all_tasks:
            self.skipTest("tasks.json 里没有作业")
        text = pack.build_pack(all_tasks)
        self.assertGreater(len(text), 200)
        self.assertIn("请帮我完成下面这些作业题", text)
        # 每份作业的标题都应出现
        for t in all_tasks:
            self.assertIn(t["title"], text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

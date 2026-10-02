"""task_parser.py 单测：覆盖作答页解析的各种情况。

跑法：python tests/test_task_parser.py
（不联网、不需要学习通账号，可随时回归）

⚠️ 样本来源说明（别把构造样本当实测）：
  * 「程序题」用的是**真实结构**（照 debug/raw_html/task_probe.html 抄的）；
  * 「单选 / 多选 / 判断 / 附件」这些题型**手上没有真实样本**，
    样本是按通用结构构造的 —— 它们只保证「解析器不会崩、能抽出东西」，
    不代表平台真实页面的字段一定长这样。等抓到真实样本再回来校准。
  * 真实样本回归在 TestRealSample 里，样本文件在就一定会跑。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import task_parser as T  # noqa: E402

# ── 真实结构：程序题（照 task_probe.html 抄）───────────────
PROGRAM_Q = """
<div class="padBom50 questionLi fontLabel singleQuesId" typename="程序题"
     id="question405661442" data="405661442">
  <h3 class="mark_name colorDeep"><span class="colorShallow">(程序题, 25分)</span></h3>
  <h1>题目 1：查看 DataFrame 并选择数据</h1>
  <p><span>输入若干天的日期。第一行输入整数<strong>n</strong>，保证 n &gt;= 3；</span></p>
  <h3>示例输入</h3>
  <pre class="line-numbers"><div class="code-tool-wrap"><div class="code-lang fl">Plain Text</div></div><code class="language-plain">4
2025-01-01 12 20</code></pre>
  <h3>作答要求</h3>
  <p><span>请使用 <strong>shape</strong> 和 <strong>iloc</strong>。不要输出额外文字。</span></p>
  <div class="clear"></div>
  <input type="hidden" id="answertype405661442" value="17">
  <input type="hidden" id="answer405661442" value="">
  <div id="procedural-405661442" class="proceduralQue" data="405661442">
    <input type="hidden" class="languageSelect" id="languageSelect405661442" value="22">
    <div class="stem_answer2">
      <div class="maskBox reset-mask" style="display:none">
        <pre><code>编辑器弹窗里的代码，绝不能被当成题目的示例</code></pre>
      </div>
    </div>
  </div>
</div>
"""

# ── 构造样本：单选题（⚠️ 无真实样本，按通用结构写）────────
SINGLE_Q = """
<div class="questionLi" typename="单选题" id="question900001" data="900001">
  <h3 class="mark_name"><span class="colorShallow">(单选题, 2分)</span></h3>
  <h1>下列哪个是 Pandas 读取 CSV 的函数？</h1>
  <ul class="Zy_ulTop">
    <li><label><input type="radio" name="ans900001" value="A">read_csv</label></li>
    <li><label><input type="radio" name="ans900001" value="B">read_excel</label></li>
    <li><label><input type="radio" name="ans900001" value="C">open_csv</label></li>
  </ul>
  <div class="clear"></div>
  <input type="hidden" id="answertype900001" value="0">
</div>
"""

# ── 构造样本：多选 + 附件（⚠️ 无真实样本）─────────────────
MULTI_Q = """
<div class="questionLi" typename="多选题" id="question900002" data="900002">
  <h3 class="mark_name"><span class="colorShallow">(多选题, 4分)</span></h3>
  <h1>下列属于 DataFrame 属性的有？</h1>
  <ul>
    <li><label><input type="checkbox" value="A">shape</label></li>
    <li><label><input type="checkbox" value="B">columns</label></li>
  </ul>
  <div class="clear"></div>
</div>
"""

UPLOAD_Q = """
<div class="questionLi" typename="简答题" id="question900003" data="900003">
  <h3 class="mark_name"><span class="colorShallow">(简答题, 20分)</span></h3>
  <h1>请提交本项目的设计文档</h1>
  <p>完成后请上传附件。</p>
  <div class="clear"></div>
</div>
"""

# ── ✅ 真实结构（照 2026-10-02 抓下来的 task_55563943.html 抄）──
# 关键：**整段题干就在 h3.mark_name 里面**（在 span.colorShallow 之后），
#       而选项在 input#answer 之后的 div.stem_answer 里，两处都不在「h3 的兄弟节点」上。
REAL_CHOICE_Q = """
<div class="padBom50 questionLi fontLabel singleQuesId" typename="单选题"
     id="question406181279" data="406181279" aria-label="题目 1. ">
  <h3 class="mark_name colorDeep fontLabel workTextWrap" tabindex="0" role="option">1.
    <span class="colorShallow">(单选题, 1分)</span>
    以习近平同志为核心的党中央围绕(&nbsp;&nbsp;&nbsp;&nbsp;)的重大时代课题，提出一系列新理念新思想新战略。
  </h3>
  <div class="clear"></div>
  <input type="hidden" id="answertype406181279" name="answertype406181279" value="0" />
  <input type="hidden" id="answer406181279" name="answer406181279" value="" />
  <div class="stem_answer qtDetail">
    <div class="clearfix answerBg workTextWrap">
      <span class="choice406181279 num_option fl" data="A">A</span>
      <div class="fl answer_p"><p>建设什么样的长期执政的马克思主义政党</p></div>
    </div>
    <div class="clearfix answerBg workTextWrap">
      <span class="choice406181279 num_option fl" data="B">B</span>
      <div class="fl answer_p"><p>我国社会主义经济建设、政治建设、文化建设</p></div>
    </div>
    <div class="clearfix answerBg workTextWrap">
      <span class="choice406181279 num_option fl" data="C">C</span>
      <div class="fl answer_p"><p>什么是新时代社会主义政党</p></div>
    </div>
    <div class="clearfix answerBg workTextWrap">
      <span class="choice406181279 num_option fl" data="D">D</span>
      <div class="fl answer_p"><p>建设什么样的社会主义现代化强国</p></div>
    </div>
  </div>
</div>
"""

# ── ✅ 真实结构（照 2026-10-02 抓下来的 task_55681499.html 抄）──
# 关键：h1 标题**嵌在 h3 里面**（早先样本里它在 h3 之后的兄弟节点上）；
#       代码模板在 textarea.code-editor 里，是学生要补代码的地方。
REAL_PROGRAM_Q = """
<div class="padBom50 questionLi fontLabel singleQuesId" typename="程序题"
     id="question405646243" data="405646243" aria-label="题目 1. ">
  <h3 class="mark_name colorDeep fontLabel workTextWrap" tabindex="0" role="option">1.
    <span class="colorShallow">(程序题, 25分)</span>
    <h1>题目 1：统计一个景区的游客总量</h1>
  </h3>
  <p><span style="text-wrap-mode: nowrap;">某景区连续n天的游客量以文本形式输入，每行一个数字。请计算游客总量。</span></p>
  <h3>输入格式</h3>
  <p><span style="text-wrap-mode: nowrap;">第一行输入天数 n。</span></p>
  <h3>作答要求</h3>
  <p><span style="text-wrap-mode: nowrap;">请只在模板标有“【在此补充代码】”的位置补充代码。</span></p>
  <div class="clear"></div>
  <input type="hidden" id="answertype405646243" name="answertype405646243" value="17" />
  <input type="hidden" id="answer405646243" name="answer405646243" value="" />
  <div id="procedural-405646243" class="proceduralQue" data="405646243">
    <input type="hidden" class="languageSelect" id="languageSelect405646243" value="22" />
    <div class="stem_answer2">
      <div class="EidtBox marBom20 codeEditorBoxDiv">
        <textarea class="code-editor">def get_total_tourist(values):
    total = 0
    # 【在此补充代码】
    return total</textarea>
      </div>
    </div>
  </div>
</div>
"""

SECTION_HEAD_1 = '<h2 class="type_tit" tabindex="0" role="option">一. 单选题（共20题，20分）</h2>'
SECTION_HEAD_2 = '<h2 class="type_tit" tabindex="0" role="option">二. 程序题（共3题，100分）</h2>'

# ── ✅ 真实结构：多选题（照 task_55563943.html 抄）──────────
# 关键：多选题的字母 span 是 **num_option_dx**，单选是 num_option。
#       用 .num_option 精确匹配会把多选题的 A/B/C 全丢掉（实测踩过）。
REAL_MULTI_Q = """
<div class="questionLi" typename="多选题" id="question406181299" data="406181299"
     aria-label="题目 21. ">
  <h3 class="mark_name colorDeep fontLabel workTextWrap" tabindex="0" role="option">21.
    <span class="colorShallow">(多选题, 2分)</span>
    习近平党建思想中的“十四个坚持”涵盖面广、系统完整。下列属于“十四个坚持”内容的有(&nbsp;&nbsp;)
  </h3>
  <div class="clear"></div>
  <input type="hidden" id="answertype406181299" name="answertype406181299" value="1" />
  <input type="hidden" id="answer406181299" name="answer406181299" value="" />
  <div class="stem_answer qtDetail ">
    <div class="clearfix answerBg workTextWrap" onclick="addMultipleChoice(this);"
         tabindex="0" role="checkbox" aria-label='A 坚持党的领导是中国特色社会主义最本质的特征选择'
         qid="406181299" qtype="1">
      <span aria-hidden="true" data="A" class="choice406181299 num_option_dx fl " tabindex="-1">A</span>
      <div aria-hidden="true" class="fl answer_p" tabindex="-1"><p>坚持党的领导是中国特色社会主义最本质的特征</p></div>
    </div>
    <div class="clearfix answerBg workTextWrap" onclick="addMultipleChoice(this);"
         tabindex="0" role="checkbox" aria-label='B 坚持以经济建设为中心选择'
         qid="406181299" qtype="1">
      <span aria-hidden="true" data="B" class="choice406181299 num_option_dx fl " tabindex="-1">B</span>
      <div aria-hidden="true" class="fl answer_p" tabindex="-1"><p>坚持以经济建设为中心</p></div>
    </div>
  </div>
</div>
"""


def page(*divs: str) -> str:
    return "<html><head><title>作业作答</title></head><body>" + "".join(divs) + "</body></html>"


class TestScoreAndNumber(unittest.TestCase):
    def test_score_from_header(self):
        self.assertEqual(T.parse_score("(程序题, 25分)"), 25.0)
        self.assertEqual(T.parse_score("(多选题, 2.5分)"), 2.5)
        self.assertIsNone(T.parse_score("(程序题)"))
        self.assertIsNone(T.parse_score(""))

    def test_number_from_header(self):
        self.assertEqual(T.parse_number("1."), 1)
        self.assertEqual(T.parse_number("12、"), 12)
        self.assertIsNone(T.parse_number("题目"))


class TestProgramQuestion(unittest.TestCase):
    def setUp(self):
        self.r = T.parse_task_page(page(PROGRAM_Q))
        self.q = self.r["questions"][0]

    def test_page_ok(self):
        self.assertTrue(self.r["ok"])
        self.assertEqual(self.r["warnings"], [])
        self.assertEqual(self.r["page_title"], "作业作答")

    def test_basic_fields(self):
        self.assertEqual(self.q["qid"], "405661442")
        self.assertEqual(self.q["typename"], "程序题")
        self.assertEqual(self.q["score"], 25.0)
        self.assertEqual(self.q["answer_kind"], "代码题")
        self.assertEqual(self.q["language"], "22")

    def test_title(self):
        self.assertEqual(self.q["title"], "题目 1：查看 DataFrame 并选择数据")

    def test_sections_split(self):
        self.assertIn("示例输入", self.q["sections"])
        self.assertIn("作答要求", self.q["sections"])
        self.assertIn("2025-01-01", self.q["sections"]["示例输入"])
        self.assertIn("shape", self.q["sections"]["作答要求"])

    def test_inline_tags_not_broken(self):
        # 「整数<strong>n</strong>，保证」必须接成一行，不能被拆成三行
        self.assertIn("第一行输入整数n，保证 n >= 3；", self.q["body_text"])
        self.assertNotIn("整数\nn\n", self.q["body_text"])

    def test_code_blocks_only_from_stem(self):
        # 编辑器弹窗里的 <pre> 不算题目的示例代码块
        texts = " ".join(b["text"] for b in self.q["code_blocks"])
        self.assertIn("2025-01-01 12 20", texts)
        self.assertNotIn("编辑器弹窗", texts)
        self.assertEqual(len(self.q["code_blocks"]), 1)
        self.assertEqual(self.q["code_blocks"][0]["lang"], "Plain Text")

    def test_no_options_for_program_question(self):
        self.assertEqual(self.q["options"], [])

    def test_example_block_keeps_newlines(self):
        # 示例输入一行一个，换行是**数据**：压掉了就没法照着验代码了（曾经压掉过）
        example = self.q["sections"]["示例输入"]
        self.assertEqual(example.splitlines()[0], "4")
        self.assertIn("2025-01-01 12 20", example.splitlines()[1])

    def test_code_toolbar_text_excluded(self):
        # 代码块上方那个「Plain Text」是工具条，不是题目内容
        self.assertNotIn("Plain Text", self.q["sections"]["示例输入"])
        self.assertNotIn("Plain Text", self.q["body_text"])

    def test_html_kept_for_fallback(self):
        self.assertIn("<h1>", self.q["body_html"])
        self.assertIn("iloc", self.q["body_html"])


class TestChoiceQuestions(unittest.TestCase):
    """⚠️ 构造样本，无真实页面验证 —— 只保证不崩、能抽到选项与题型。"""

    def test_single_choice(self):
        q = T.parse_task_page(page(SINGLE_Q))["questions"][0]
        self.assertEqual(q["typename"], "单选题")
        self.assertEqual(q["score"], 2.0)
        self.assertEqual(q["answer_kind"], "单选")
        self.assertEqual(len(q["options"]), 3)
        self.assertTrue(any("read_csv" in o for o in q["options"]))

    def test_multi_choice(self):
        q = T.parse_task_page(page(MULTI_Q))["questions"][0]
        self.assertEqual(q["answer_kind"], "多选")
        self.assertEqual(len(q["options"]), 2)

    def test_upload_question(self):
        q = T.parse_task_page(page(UPLOAD_Q))["questions"][0]
        self.assertEqual(q["typename"], "简答题")
        self.assertEqual(q["answer_kind"], "简答")
        self.assertTrue(q["need_upload"])

    def test_summary_counts(self):
        r = T.parse_task_page(page(SINGLE_Q, MULTI_Q, UPLOAD_Q))
        s = r["summary"]
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["score"], 26.0)          # 2 + 4 + 20
        self.assertEqual(s["kinds"], {"单选": 1, "多选": 1, "简答": 1})
        self.assertEqual(s["need_upload"], 1)


class TestDegeneratePages(unittest.TestCase):
    def test_no_question_container_falls_back(self):
        r = T.parse_task_page("<html><body><p>暂无作业内容</p></body></html>")
        self.assertFalse(r["ok"])
        self.assertTrue(r["warnings"])
        self.assertIn("暂无作业内容", r["fallback_text"])

    def test_empty_html(self):
        r = T.parse_task_page("")
        self.assertFalse(r["ok"])
        self.assertEqual(r["questions"], [])

    def test_verify_page_detected_by_shared_helper(self):
        # 解析模块不判断风控，但复用的特征函数必须能认出来（抓取层靠它熔断）
        verify = "<html><body>【9010】操作异常，请输入图片中的验证码</body></html>"
        self.assertTrue(T.looks_like_verify_page(verify))
        self.assertFalse(T.looks_like_verify_page(page(PROGRAM_Q)))

    def test_login_page_detected_by_shared_helper(self):
        self.assertTrue(T.looks_like_login_page("<html>请登录</html>"))


class TestRealStructures(unittest.TestCase):
    """✅ 真实结构回归（2026-10-02 实抓样本）。

    这些断言对应的是**真实踩过的坑**，不是想象出来的：
    第一次端到端实测时，题干整段没读到、选项一个没抽到，
    就是因为题干在 h3 里、选项在 input#answer 之后，都不在「h3 的兄弟节点」上。
    """

    def test_choice_stem_inside_header(self):
        q = T.parse_task_page(page(REAL_CHOICE_Q))["questions"][0]
        self.assertEqual(q["typename"], "单选题")
        self.assertEqual(q["score"], 1.0)
        self.assertEqual(q["answer_kind"], "单选")
        # 题干整段在 h3 里 —— 必须被读到，而且不能带「1.」和「(单选题, 1分)」
        self.assertIn("以习近平同志为核心的党中央围绕", q["body_text"])
        self.assertNotIn("(单选题, 1分)", q["body_text"])
        self.assertFalse(q["body_text"].startswith("1."))
        self.assertEqual(q["warnings"], [])

    def test_choice_options_from_answerBg(self):
        q = T.parse_task_page(page(REAL_CHOICE_Q))["questions"][0]
        self.assertEqual(len(q["options"]), 4)
        self.assertTrue(q["options"][0].startswith("A."))
        self.assertIn("建设什么样的长期执政的马克思主义政党", q["options"][0])
        self.assertTrue(q["options"][3].startswith("D."))

    def test_multi_choice_letters_from_num_option_dx(self):
        # 多选题的字母 span 叫 num_option_dx —— 只认 .num_option 会把字母全丢
        q = T.parse_task_page(page(REAL_MULTI_Q))["questions"][0]
        self.assertEqual(q["answer_kind"], "多选")
        self.assertEqual(len(q["options"]), 2)
        self.assertTrue(q["options"][0].startswith("A."), q["options"][0])
        self.assertTrue(q["options"][1].startswith("B."), q["options"][1])
        self.assertIn("坚持党的领导", q["options"][0])

    def test_program_title_inside_header(self):
        q = T.parse_task_page(page(REAL_PROGRAM_Q))["questions"][0]
        # h1 嵌在 h3 里面（早先样本里它是 h3 之后的兄弟节点）
        self.assertEqual(q["title"], "题目 1：统计一个景区的游客总量")
        self.assertEqual(q["score"], 25.0)
        # 标题与题干不重复占两份
        self.assertNotIn("题目 1：统计一个景区的游客总量\n题目 1：", q["body_text"])

    def test_program_code_template_extracted(self):
        q = T.parse_task_page(page(REAL_PROGRAM_Q))["questions"][0]
        self.assertIn("def get_total_tourist(values):", q["code_template"])
        self.assertIn("【在此补充代码】", q["code_template"])
        self.assertIn("return total", q["code_template"])

    def test_program_sections_and_no_false_warning(self):
        q = T.parse_task_page(page(REAL_PROGRAM_Q))["questions"][0]
        self.assertIn("输入格式", q["sections"])
        self.assertIn("作答要求", q["sections"])
        # 页面里本来就没有示例输入/输出，不该报「没抽到」这种假警告
        self.assertEqual(q["warnings"], [])

    def test_section_titles_attached(self):
        r = T.parse_task_page(page(SECTION_HEAD_1, REAL_CHOICE_Q, SECTION_HEAD_2, REAL_PROGRAM_Q))
        self.assertEqual(r["questions"][0]["section"], "一. 单选题（共20题，20分）")
        self.assertEqual(r["questions"][1]["section"], "二. 程序题（共3题，100分）")


class TestAnyCapturedSample(unittest.TestCase):
    """通用不变量：debug/raw_html/task_*.html 里只要有**真实抓下来的**作答页就跑一遍。

    这个测试是照「第一次端到端实测为什么会崩」设计的 ——
    以后你每抓一次题目，原始响应都会留在那个目录，这个测试就自动变强。
    """

    DIR = Path(__file__).resolve().parent.parent / "debug" / "raw_html"

    def test_captured_pages_have_stem_and_options(self):
        files = sorted(self.DIR.glob("task_*.html")) if self.DIR.exists() else []
        if not files:
            self.skipTest("还没有真实抓下来的作答页（debug/raw_html/task_*.html）")
        for path in files:
            r = T.parse_task_page(path.read_text(encoding="utf-8", errors="replace"))
            with self.subTest(sample=path.name):
                self.assertTrue(r["ok"], f"{path.name} 没解出题目：{r['warnings']}")
                for q in r["questions"]:
                    self.assertTrue(q["body_text"], f"{path.name} 第 {q['number']} 题没读到题干")
                    if "选择" in (q["typename"] or ""):
                        self.assertTrue(q["options"],
                                        f"{path.name} 第 {q['number']} 题（选择题）没抽到选项")


class TestRealSample(unittest.TestCase):
    """真实样本回归：debug/raw_html/task_probe.html（该目录允许随时删，缺了就跳过）。"""

    SAMPLE = (Path(__file__).resolve().parent.parent
              / "debug" / "raw_html" / "task_probe.html")

    def setUp(self):
        if not self.SAMPLE.exists():
            self.skipTest("真实样本不在（debug/raw_html/task_probe.html 已删）")
        self.r = T.parse_task_page(self.SAMPLE.read_text(encoding="utf-8", errors="replace"))

    def test_three_questions_total_100(self):
        self.assertTrue(self.r["ok"])
        self.assertEqual(self.r["summary"]["total"], 3)
        self.assertEqual(self.r["summary"]["score"], 100.0)

    def test_all_program_questions(self):
        self.assertEqual([q["typename"] for q in self.r["questions"]],
                         ["程序题", "程序题", "程序题"])
        self.assertEqual([q["score"] for q in self.r["questions"]], [25.0, 35.0, 40.0])
        self.assertEqual([q["answer_kind"] for q in self.r["questions"]],
                         ["代码题", "代码题", "代码题"])

    def test_titles(self):
        self.assertEqual([q["title"] for q in self.r["questions"]], [
            "题目 1：查看 DataFrame 并选择数据",
            "题目 2：筛选并排序高客流记录",
            "题目 3：制作景区统计汇总表",
        ])

    def test_example_input_preserved(self):
        q1 = self.r["questions"][0]
        self.assertIn("2025-01-01 12 20", q1["sections"]["示例输入"])
        self.assertIn("日期,九寨沟,张家界", q1["sections"]["示例输出"])
        self.assertIn("不要输出额外文字", q1["sections"]["作答要求"])

    def test_example_newlines_intact_on_real_page(self):
        q1 = self.r["questions"][0]
        self.assertEqual(q1["sections"]["示例输入"].splitlines(), [
            "4", "2025-01-01 12 20", "2025-01-02 18 16",
            "2025-01-03 26 24", "2025-01-04 20 15",
        ])
        self.assertEqual(q1["sections"]["示例输出"].splitlines(), [
            "4 3", "日期,九寨沟,张家界", "76", "12,18,26",
        ])


if __name__ == "__main__":
    unittest.main(verbosity=2)

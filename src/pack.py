"""把抓到的题目**打包成一份可以直接丢给 AI 的文档**。

和 `tasks.to_markdown()` 的区别（两者用途不同，别互相替代）：

| | `to_markdown`（已有的） | 本模块 |
|---|---|---|
| 给谁看 | **人**（离线翻阅、存档） | **AI**（整段粘贴过去） |
| 带什么 | 课程、老师、状态、剩余时间、原页面 URL | 题目本身 + 一句明确的作答要求 |
| 藏着什么 | 全都写 | 去掉 URL / 抓取时间这类对 AI 无用的噪声 |

**⚠️ 边界（这条不能改）**：本模块只**整理和投递**题目，不生成答案。
真正产答案的是你在 AI 网页那边——题目是你自己发出去的，那边的回答与本程序无关。
所以这里给的是一份「提问模板」，不是「答案生成器」。
"""
from __future__ import annotations

from typing import Any

# 打包时给 AI 的指令。刻意写得具体，省得对方只给答案不给代码/不按格式。
# 想换风格就改这里 —— 它是这份文档里唯一"我们说的话"。
INSTRUCTION = """请帮我完成下面这些作业题。

要求：
1. **每道题给出答案**，并简要说明为什么（尤其是选择题，说明其他选项错在哪）。
2. **编程题**：给出完整可运行的代码，语言按题目指定的；如果题目给了代码模板，
   就按模板的结构补全（保留原有函数名和签名），不要另起一套写法。
3. **严格按题号顺序**回答，每条开头标「第 N 题」，方便我对照。
4. 如果某道题信息不足、无法确定答案，**直接说无法确定**，不要猜。

"""


def build_pack(
    tasks: list[dict[str, Any]],
    *,
    include_instruction: bool = True,
    include_url: bool = False,
    include_meta: bool = True,
) -> str:
    """把若干份作业拼成一份 Markdown 文档。"""
    out: list[str] = []
    if include_instruction:
        out.append(INSTRUCTION.rstrip())
        out.append("")
        out.append("---")
        out.append("")

    for task in tasks:
        out.append(f"# {task.get('course_name', '')} · {task.get('title', '')}")
        out.append("")
        if include_meta:
            bits = []
            if task.get("state_text"):
                bits.append(f"状态：{task['state_text']}")
            if task.get("remain_text"):
                bits.append(f"剩余：{task['remain_text']}")
            if bits:
                out.append("（" + "；".join(bits) + "）")
                out.append("")
        if include_url and task.get("url"):
            out.append(f"原页面：{task['url']}")
            out.append("")

        if task.get("error"):
            out.append(f"> ⚠️ {task['error']}")
            out.append("")

        last_section: str | None = None
        for q in task.get("questions") or []:
            section = q.get("section") or ""
            if section and section != last_section:
                out.append(f"## {section}")
                out.append("")
                last_section = section

            num = q.get("number") or "?"
            score = f"，{q['score']} 分" if q.get("score") else ""
            out.append(f"### 第 {num} 题（{q.get('typename') or '未知题型'}{score}）")
            out.append("")
            if q.get("title"):
                out.append(f"**{q['title']}**")
                out.append("")

            secs = q.get("sections") or {}
            for name, body in secs.items():
                if not body:
                    continue
                if name == "_intro" or name == q.get("title"):
                    out.append(body)
                    out.append("")
                    continue
                # 「示例输入/输出」这类要保住原样，用代码块包起来
                is_code = name.startswith("示例") or "示例" in name
                out.append(f"**{name}**")
                out.append("")
                if is_code:
                    out.append("```")
                    out.append(body)
                    out.append("```")
                else:
                    out.append(body)
                out.append("")

            options = q.get("options") or []
            if options:
                out.extend(f"- {o}" for o in options)
                out.append("")

            if q.get("code_template"):
                out.append("**代码模板**")
                out.append("")
                out.append("```")
                out.append(q["code_template"])
                out.append("```")
                out.append("")
        out.append("---")
        out.append("")

    # 末尾再去掉多余空行
    text = "\n".join(out).rstrip()
    while text.endswith("---"):
        text = text[:-3].rstrip()
    return text + "\n"


def suggest_filename(tasks: list[dict[str, Any]]) -> str:
    """给打包文件起个名字。"""
    if not tasks:
        return "作业题目.md"
    if len(tasks) == 1:
        t = tasks[0]
        name = f"{t.get('course_name', '')}_{t.get('title', '')}"
    else:
        courses = {t.get("course_name") for t in tasks}
        name = next(iter(courses)) if len(courses) == 1 else "全部待办作业"
        name = f"{name}_共{len(tasks)}份"
    bad = '\\/:*?"<>|\r\n\t'
    for ch in bad:
        name = name.replace(ch, "_")
    return name.strip(" ._")[:80] + ".md"

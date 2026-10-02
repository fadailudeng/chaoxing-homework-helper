"""学习通「作业作答页」HTML 解析。

纯函数、不联网、无副作用 —— 方便配套单测（见 tests/test_task_parser.py）。

页面结构（实测样本 debug/raw_html/task_probe.html，页面标题「作业作答」）：
    div.questionLi[typename="程序题"][id="question<qid>"][data="<qid>"]
      ├─ h3.mark_name                 「1.」+ span.colorShallow「(程序题, 25分)」
      ├─ <题干区>                      h1 标题 / p 正文 / h3 小节 / pre>code 示例
      ├─ div.clear                    题干结束的哨兵
      ├─ input#answertype<qid>         题型编号（实测程序题=17）
      ├─ input#answer<qid>             作答内容（提交时读这个）
      └─ div#procedural-<qid>.proceduralQue    在线代码编辑器（内含 languageSelect）

⚠️ 本模块**只做「读」**：把题干、小节、示例、分值、作答方式抓成结构化数据。
   不生成答案、不填写作答框、不提交 —— 这是本项目的功能边界。

⚠️ 实测局限性（别当成已知全部）：
   手上只有「程序题」的真实样本（3 道，来自 task_probe.html）。
   单选 / 多选 / 判断 / 填空 / 简答 / 附件类的细节结构**没有真实样本验证过**，
   选项抽取是按通用结构写的 best-effort。所以每条题目都会额外保留
   `body_text` 与 `body_html` 原文兜底 —— 就算结构化字段没认准，原文一定在。
"""
from __future__ import annotations

import copy
import re
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

# 复用列表页那套风控 / 登录页特征，别在两处各写一份
from parser import looks_like_login_page, looks_like_verify_page  # noqa: F401

# 题干结束的哨兵：碰到这些就说明题干区完了，后面是作答控件
_STEM_END_ID_PREFIX = ("answertype", "answer", "procedural-", "answerInfo")
_STEM_END_CLASS = ("clear", "stem_answer2")

# 题干里的小节标题（h1~h6）被当成分段点
_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

_RE_SCORE = re.compile(r"(\d+(?:\.\d+)?)\s*分")
_RE_NUMBER = re.compile(r"^\s*(\d+)\s*[.、]")

# 作答方式判定（按优先级）
_KIND_RULES = (
    ("代码题", ("程序题", "编程题", "代码题")),
    ("单选", ("单选题", "单选")),
    ("多选", ("多选题", "多选")),
    ("判断", ("判断题", "判断")),
    ("填空", ("填空题", "填空")),
    ("简答", ("简答题", "简答", "论述题", "名词解释")),
)


# 块级元素之间才换行；strong/span/code 这类行内元素必须接在一起，
# 否则「第一行输入整数<strong>n</strong>，保证…」会被拆成三行，读起来是断的。
_BLOCK_TAGS = frozenset((
    "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol",
    "pre", "table", "thead", "tbody", "tr", "td", "th",
    "section", "article", "blockquote", "hr", "br",
))


def _extract_text(root: Tag) -> str:
    """块级元素之间换行，行内元素直接相接。"""
    parts: list[str] = []
    for node in root.descendants:
        if isinstance(node, NavigableString):
            parts.append(re.sub(r"[ \t]+", " ", str(node)))
        elif isinstance(node, Tag) and node.name in _BLOCK_TAGS:
            parts.append("\n")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in "".join(parts).splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _clean_pre(el: Tag) -> str:
    """取 <pre> 的正文：原样保留换行与缩进，并剔除「Plain Text」工具条。"""
    clone = copy.copy(el)
    for junk in clone.select(".code-tool-wrap"):
        junk.decompose()
    return clone.get_text().strip("\n")


def _text(el: Any) -> str:
    """取纯文本。

    三条规则，都是实测逼出来的：
      * 块级元素（p / div / h1…）之间换行，行内元素（strong / span）必须直接相接 ——
        否则「第一行输入整数<strong>n</strong>，保证…」会被拆成三行，读起来是断的；
      * `<pre>` 里的换行是**数据**（示例输入一行一个），必须原样保留，
        而且不能把代码块上方那个「Plain Text」工具条当成内容 ——
        这里先把每个 pre 抠出来存好、留个占位符，等整段清理完再原样填回去。
    """
    if el is None:
        return ""
    if not isinstance(el, Tag):
        return str(el).strip()
    if el.name == "pre":
        return _clean_pre(el)

    clone = copy.copy(el)
    stash: list[str] = []
    for pre in clone.select("pre"):
        stash.append(_clean_pre(pre))
        pre.replace_with(f"\x00{len(stash) - 1}\x00")

    out = _extract_text(clone)
    for i, code in enumerate(stash):
        out = out.replace(f"\x00{i}\x00", code)
    return out


def _is_stem_end(el: Tag) -> bool:
    """这个元素是不是「作答区」的开始（题干到它为止）。"""
    if el.name == "input":
        eid = str(el.get("id") or "")
        if eid.startswith(_STEM_END_ID_PREFIX):
            return True
    eid = str(el.get("id") or "")
    if eid.startswith("procedural-") or eid.startswith("answerInfo"):
        return True
    return bool(set(el.get("class") or []) & set(_STEM_END_CLASS))


def _collect_stem(header: Tag | None) -> list[Any]:
    """从 h3.mark_name 之后一路收，直到作答区哨兵。返回元素列表（含裸文本）。"""
    if header is None:
        return []
    out: list[Any] = []
    for sib in header.next_siblings:
        if isinstance(sib, NavigableString):
            if str(sib).strip():
                out.append(sib)
            continue
        if not isinstance(sib, Tag):
            continue
        if _is_stem_end(sib):
            break
        out.append(sib)
    return out


def _split_sections(stem: list[Any]) -> tuple[dict[str, str], str]:
    """按小节标题把题干切段。

    返回 (小节字典, 全文)。小节字典形如
    {"_intro": "…", "输入格式": "…", "示例输入": "4\\n2025-01-01 12 20"}。
    """
    sections: dict[str, list[str]] = {}
    current = "_intro"
    sections[current] = []

    for el in stem:
        if isinstance(el, Tag) and el.name in _HEADING_TAGS:
            title = _text(el)
            if title:
                current = title
                sections.setdefault(current, [])
                continue
        piece = _text(el)
        if piece:
            sections.setdefault(current, []).append(piece)

    merged = {k: "\n".join(v).strip() for k, v in sections.items() if "\n".join(v).strip()}
    body = "\n".join(p for p in merged.values() if p).strip()
    return merged, body


def parse_score(text: str | None) -> float | None:
    """「(程序题, 25分)」→ 25.0。"""
    m = _RE_SCORE.search(text or "")
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def parse_number(text: str | None) -> int | None:
    """「1.」→ 1。"""
    m = _RE_NUMBER.match(text or "")
    return int(m.group(1)) if m else None


def answer_kind(typename: str, div: Tag) -> str:
    """这道题要怎么作答：代码题 / 单选 / 多选 / 判断 / 填空 / 简答 / 附件 / 文本 / 未知。"""
    name = typename or ""
    for kind, keys in _KIND_RULES:
        if any(k in name for k in keys):
            # 名称说是选择题，但实际可能是在线判题 —— 以页面上的控件为准再核一次
            if div.select_one("input[type=radio]"):
                return "单选" if kind in ("判断", "单选") else kind
            if div.select_one("input[type=checkbox]"):
                return "多选"
            return kind
    if div.select_one("div.proceduralQue"):
        return "代码题"
    if div.select_one("input[type=file]"):
        return "附件上传"
    if div.select_one("input[type=radio]"):
        return "单选"
    if div.select_one("input[type=checkbox]"):
        return "多选"
    if div.select_one("textarea"):
        return "文本输入"
    return "未知"


def need_upload(div: Tag) -> bool:
    """这道题要不要交附件（文件上传）。"""
    if div.select_one("input[type=file]"):
        return True
    return "上传附件" in _text(div) or "附件" in _text(div)


def _collect_options(div: Tag, stem: list[Any]) -> list[str]:
    """选择题选项。

    ✅ 实测结构（debug 样本 task_55563943.html，30 道选择题，2026-10-02）：
        div.stem_answer.qtDetail
          div.clearfix.answerBg.workTextWrap
            span.num_option[data=A]   «A»
            div.answer_p > p          «选项正文»

    ⚠️ 注意：选项**不在题干区里**，而是在 input#answer 之后，
       所以不能靠 _collect_stem 收 —— 得单独从 div.answerBg 抓。
       另外保留 radio/checkbox 与 <ul><li> 两条兜底路径（改版 / 别的题型用得上）。
    """
    opts: list[str] = []

    for box in div.select("div.answerBg"):
        # ⚠️ 单选题的字母 span 是 num_option，多选题是 num_option_dx ——
        #    用 .num_option 精确匹配会漏掉多选（实测：多选题选项因此全丢了 A/B/C 前缀）。
        letter_el = box.select_one('[class*="num_option"]')
        letter = ""
        if letter_el is not None:
            letter = str(letter_el.get("data") or _text(letter_el)).strip()
        body = _text(box.select_one("div.answer_p")) or _text(box)
        if body:
            opts.append(f"{letter}. {body}" if letter else body)

    if not opts:
        for box in div.select("li"):
            if box.select_one("input[type=radio], input[type=checkbox]") is None:
                continue
            label = _text(box.select_one("label")) or _text(box)
            if label:
                opts.append(label)

    if not opts:
        for el in stem:
            if isinstance(el, Tag) and el.name == "ul":
                for li in el.select("li"):
                    t = _text(li)
                    if t:
                        opts.append(t)
                if opts:
                    break

    # 去掉重复（同一条文字可能被容器和 label 各抓一次）
    seen: set[str] = set()
    uniq: list[str] = []
    for o in opts:
        if o not in seen:
            seen.add(o)
            uniq.append(o)
    return uniq


def _header_stem(header: Tag | None) -> str:
    """h3.mark_name 里除去「1.」和「(单选题, 1分)」之后剩下的**题干**。

    ⚠️ 这是本模块最容易踩的坑，实测三种真实页面各不相同：
      * 选择题：**整段题干就塞在 h3 里** ——
        「1. (单选题, 1分) 以习近平同志为核心的党中央围绕( )的重大时代课题…」
      * 程序题（新页面）：h3 里还嵌着 <h1>题目 1：统计一个景区的游客总量</h1>
      * 程序题（早先样本 task_probe.html）：h3 里只有「1.」，题干在 h3 **之后**的兄弟节点
    所以题干 = h3 内部剩余文字 **+** h3 之后的兄弟节点，两边都要收，
    只收一边就会像第一次实测那样「没读到题干正文」。
    """
    if header is None:
        return ""
    clone = copy.copy(header)
    for junk in clone.select("span.colorShallow"):
        junk.decompose()
    return _RE_NUMBER.sub("", _text(clone), count=1).strip()


def parse_question(div: Tag, section: str = "") -> dict[str, Any]:
    """解析一道题。section 是它所属的大题标题（<h2 class="type_tit">一. 单选题…</h2>）。"""
    qid = str(div.get("data") or div.get("id") or "").replace("question", "")
    typename = str(div.get("typename") or "").strip()

    header = div.select_one("h3.mark_name")
    score = parse_score(_text(header))
    number = parse_number(_text(header))
    header_text = _header_stem(header)

    stem = _collect_stem(header)
    sections, body_text = _split_sections(stem)
    body_html = "".join(str(el) for el in stem).strip()

    # 题目标题：h1 可能在 h3 里面（新页面），也可能在 h3 之后的题干区里（早先样本）
    title = ""
    h1 = header.select_one("h1") if header is not None else None
    if h1 is not None:
        title = _text(h1)
    if not title:
        for el in stem:
            if isinstance(el, Tag) and el.name == "h1":
                title = _text(el)
                break

    # 把 h3 里那段题干并进正文；它跟标题重复时就不重复放一遍
    if header_text and header_text != title:
        existing = sections.pop("_intro", "")
        merged = f"{header_text}\n{existing}".strip() if existing else header_text
        sections = {"_intro": merged, **sections}
        body_text = f"{header_text}\n{body_text}".strip()

    # ⚠️ 只在**题干区**里找 <pre>：题目容器里还塞着代码编辑器工具栏和一票弹窗，
    #    直接 div.select("pre") 会把它们全收进来（实测第 1 题因此从 2 个变成 26 个）。
    blocks: list[dict[str, str]] = []
    for el in stem:
        if not isinstance(el, Tag):
            continue
        pres = [el] if el.name == "pre" else el.select("pre")
        for pre in pres:
            code = pre.select_one("code")
            lang = _text(pre.select_one(".code-lang"))
            text = _text(code) if code is not None else _text(pre)
            if text:
                blocks.append({"lang": lang, "text": text})

    # 在线判题的代码模板：学生要往这个模板里补代码（作答要求常写「【在此补充代码】」）
    tpl_el = div.select_one("textarea.code-editor")
    code_template = _text(tpl_el).strip() if tpl_el is not None else ""

    lang_input = div.select_one("input.languageSelect")
    warnings: list[str] = []
    if not typename:
        warnings.append("没读到 typename（题型）")
    if not body_text:
        warnings.append("没读到题干正文")
    if not _collect_options(div, stem) and typename and "选择" in typename:
        warnings.append("选择题但没抽到选项")

    options = _collect_options(div, stem)
    return {
        "qid": qid,
        "number": number,
        "typename": typename,
        "score": score,
        "section": section,
        "title": title,
        "body_text": body_text,
        "body_html": body_html,
        "sections": sections,
        "code_blocks": blocks,
        "code_template": code_template,
        "options": options,
        "answer_kind": answer_kind(typename, div),
        "need_upload": need_upload(div),
        "language": str(lang_input.get("value")) if lang_input is not None else "",
        "warnings": warnings,
    }


def _section_titles(soup: Tag) -> dict[int, str]:
    """给每道题标出它所属的大题标题。

    实测页面是按大题分组的：
        <h2 class="type_tit">一. 单选题（共20题，20分）</h2>
        <div class="questionLi" typename="单选题">…
    把这行带上，界面上能分组，也能一眼核对「这大题一共几题」。
    """
    found: dict[int, str] = {}
    current = ""
    for el in soup.descendants:
        if not isinstance(el, Tag):
            continue
        classes = el.get("class") or []
        if el.name == "h2" and "type_tit" in classes:
            current = _text(el)
        elif el.name == "div" and "questionLi" in classes:
            found[id(el)] = current
    return found


def parse_task_page(html: str) -> dict[str, Any]:
    """解析一张「作业作答页」。返回：

    {
      "ok": bool,                  # 有没有解出题目
      "page_title": str,
      "questions": [...],
      "summary": {"total": n, "score": x, "kinds": {...}},
      "fallback_text": str,        # 没解出题目时的兜底正文（保证不白抓）
      "warnings": [...],
    }

    ⚠️ 不判断风控/登录 —— 那是抓取层的事（见 tasks.py），
       因为「解析」和「这个响应能不能用」是两件事，分开测更干净。
    """
    soup = BeautifulSoup(html or "", "lxml")
    title_el = soup.find("title")
    page_title = _text(title_el)

    divs = soup.select("div.questionLi")
    sections_of = _section_titles(soup)
    questions = [parse_question(d, sections_of.get(id(d), "")) for d in divs]

    warnings: list[str] = []
    if not questions:
        warnings.append("没找到题目容器 div.questionLi —— 可能是已提交页 / 互评页 / 平台改版")

    fallback = ""
    if not questions:
        body = soup.find("body") or soup
        fallback = _text(body)[:5000]

    return {
        "ok": bool(questions),
        "page_title": page_title,
        "questions": questions,
        "summary": summarize(questions),
        "fallback_text": fallback,
        "warnings": warnings,
    }


def summarize(questions: list[dict[str, Any]]) -> dict[str, Any]:
    """题量、总分、题型分布 —— 界面上给个一眼可见的概览。"""
    kinds: dict[str, int] = {}
    for q in questions:
        kinds[q["answer_kind"]] = kinds.get(q["answer_kind"], 0) + 1
    total_score = sum(q["score"] or 0 for q in questions)
    return {
        "total": len(questions),
        "score": round(total_score, 1) if total_score else None,
        "kinds": kinds,
        "need_upload": sum(1 for q in questions if q["need_upload"]),
    }

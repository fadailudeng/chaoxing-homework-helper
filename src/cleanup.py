"""清理缓存：**只删明确列出的垃圾，其余一律不碰**。

为什么单独一个模块（而不是像原来那样写死在 .bat 里）
────────────────────────────────────────────────────
原来清理范围写死在 `清理缓存.bat` 的两条 `Remove-Item` 里，两个问题：

1. **界面上点不了** —— 想清理必须去文件夹双击 bat；
2. **范围说不清** —— 「不会删什么」只写在注释里，没有代码约束，
   以后有人往里加一条 `Remove-Item data -Recurse` 也不会被拦住。

所以把「清什么 / 不清什么」收敛到这一处，并且用两条硬机制保证安全：

- **白名单**：只有 `_CLEAN_TARGETS` 里列出的路径才会被删。传入白名单外的路径直接拒绝。
- **保护清单**：`_PROTECTED` 里的路径（登录态、扫描结果、抓到的题目……）
  即使有人误加进白名单，`_guard()` 也会把它拦下来并报错。

删除前先算体积并列出清单，删完再复核；**保护清单里的东西会在开始和结束时各校验一次**，
对不上就报错——这样「清理把登录态弄丢了」不可能悄悄发生。
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

# 和 server.py 同款：本项目 src/ 下都是扁平导入（import config），
# 直接 `python src/cleanup_cli.py` 跑时父目录不在 sys.path 里，得自己加。
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402


@dataclass
class Target:
    """一个清理目标。"""

    path: Path
    why: str                 # 为什么可以删（给人看的）
    rebuild: str             # 删掉之后会怎样
    optional: bool = False   # True = 默认不删，要显式包含（如调试用的原始响应）


def clean_targets() -> list[Target]:
    """清理白名单。**只能在这里加东西**，加之前先看 `_PROTECTED`。"""
    return [
        Target(
            path=config.WEBVIEW_PROFILE_DIR,
            why="界面窗口自己的 Edge 用户目录。Edge 会往里面塞自己的组件"
                "（component_crx_cache / ProvenanceData / Edge Entity Extraction…），"
                "跟本程序的数据无关，实测能涨到 470 MB 以上",
            rebuild="Edge 会重建，所以清理后第一次开窗口会慢一点，之后还会慢慢涨——那是 Edge 的行为",
        ),
        Target(
            path=config.DEBUG_DIR / "preview_profile",
            why="截图预览测试（tests/preview_*.py）开的浏览器目录，只在跑测试时用",
            rebuild="下次跑预览测试时自动重建",
        ),
        Target(
            path=config.RAW_HTML_DIR,
            why="排查解析问题时留下的原始响应（作业列表 / 课程中间页的 HTML）。"
                "功能正常时用不到，只有平台改版、解析失效了才需要回头看",
            rebuild="下次扫描 / 抓题时会重新写入",
            optional=True,
        ),
        Target(
            path=config.DEBUG_DIR / "course_list_raw.json",
            why="课程列表接口的原始返回，只在排查「漏课」时用（要看就用 tests/inspect_courses.py）",
            rebuild="跑 tests/inspect_courses.py 会重新生成",
            optional=True,
        ),
        # debug 根目录下由测试脚本生成的截图（tests/preview_ui.py、preview_dashboard.py
        # 和人工排查时留下的）。逐个列出来而不是删整个 debug 目录 ——
        # 因为 debug 里还躺着 homework_backup_*.json 这种**数据备份**，不能一起清掉。
        *[
            Target(
                path=config.DEBUG_DIR / name,
                why="测试 / 排查时生成的截图或临时页面，看过就没用了",
                rebuild="下次跑 tests/preview_ui.py 会重新生成",
                optional=True,
            )
            for name in (
                "ui_preview.png",
                "ui_picker.png",
                "ui_picker_todo.png",
                "ui_blocked.png",
                "verify_page.png",
                "preview.png",
                "preview.html",
            )
        ],
    ]


def _protected() -> list[tuple[Path, str]]:
    """**绝对不能删**的东西。清理前后各校验一次，对不上就报错。

    返回 (路径, 说明)。目录只比对「还在不在」，文件额外比对大小。
    """
    return [
        (config.BROWSER_PROFILE_DIR, "登录态（删了要重新登录）"),
        (config.STATE_JSON, "登录态快照（profile 没落盘时的双保险）"),
        (config.RESULT_JSON, "扫描结果（作业列表）"),
        (config.TASKS_JSON, "抓下来的题目（结构化）"),
        (config.TASKS_DIR, "抓下来的题目（人看的 .md）"),
        (config.COURSES_CACHE, "课程列表缓存"),
        (config.SELECTION_JSON, "选课器里勾选的课程"),
        (config.SCAN_LOG, "扫描日志"),
        (config.WEB_DIR, "界面网页"),
        (config.ROOT / "src", "程序代码"),
        (config.ROOT / "assets", "图标等资源"),
    ]


# 通配符形式的保护规则（保护清单编译不出来，因为文件名带时间戳）。
# debug 根目录下的 `homework_backup_155808.json` 这类**数据备份**就靠它兜住：
# 白名单里只逐个列了要删的截图名，这里再把「备份」前缀整个禁掉，
# 以后有人往白名单里加 `debug/homework_backup_xxx.json` 也删不掉。
_PROTECTED_GLOBS: tuple[tuple[str, str], ...] = (
    ("debug/homework_backup_*.json", "作业数据的历史备份，属于数据不是缓存"),
)


def _glob_protected(path: Path) -> str | None:
    """路径命中通配符保护规则就返回说明，否则 None。"""
    try:
        rel = path.resolve().relative_to(config.ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    for pattern, label in _PROTECTED_GLOBS:
        if fnmatch(rel, pattern):
            return label
    return None


def _size_of(path: Path) -> tuple[int, int]:
    """返回 (字节数, 文件数)。路径不存在返回 (0, 0)。"""
    if not path.exists():
        return 0, 0
    if path.is_file():
        try:
            return path.stat().st_size, 1
        except OSError:
            return 0, 0
    total = 0
    count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
                count += 1
            except OSError:
                pass
    return total, count


def _fingerprint() -> dict[str, str]:
    """给保护清单拍个指纹：目录记「存在/缺失」，文件记「大小」。"""
    out: dict[str, str] = {}
    for path, _label in _protected():
        if not path.exists():
            out[str(path)] = "missing"
        elif path.is_file():
            try:
                out[str(path)] = f"{path.stat().st_size}"
            except OSError:
                out[str(path)] = "unreadable"
        else:
            out[str(path)] = "dir"
    return out


def _mb(n: int) -> float:
    return round(n / 1048576, 1)


def survey(include_optional: bool = False) -> dict:
    """**只看不删**：列出清理会命中什么、会释放多少、以及保护清单的现状。

    界面用这个接口先给用户看清楚，再决定要不要真清。
    """
    items = []
    total = 0
    for t in clean_targets():
        if t.optional and not include_optional:
            continue
        size, count = _size_of(t.path)
        if size == 0 and count == 0 and not t.path.exists():
            continue
        total += size
        items.append({
            "path": str(t.path.relative_to(config.ROOT)),
            "size_mb": _mb(size),
            "files": count,
            "why": t.why,
            "rebuild": t.rebuild,
            "optional": t.optional,
        })
    protected = [
        {
            "path": str(p.relative_to(config.ROOT)),
            "label": label,
            "exists": p.exists(),
        }
        for p, label in _protected()
    ]
    return {
        "items": items,
        "total_mb": _mb(total),
        "protected": protected,
    }


def _guard(path: Path) -> None:
    """白名单外的路径、或碰到保护清单 → 直接拒绝。

    用 resolved() 之后比对，防止 `data/../data/browser_profile` 这种绕法。
    """
    try:
        target = path.resolve()
    except OSError:
        target = path
    allowed = {t.path.resolve() for t in clean_targets()}
    if target not in allowed:
        raise ValueError(f"拒绝：{path} 不在清理白名单里")
    hit = _glob_protected(path)
    if hit:
        raise ValueError(f"拒绝：{path} 命中受保护规则「{hit}」")
    for prot, label in _protected():
        try:
            prot_r = prot.resolve()
        except OSError:
            prot_r = prot
        if target == prot_r or prot_r in target.parents:
            raise ValueError(f"拒绝：{path} 落在受保护内容「{label}」里")


def run(include_optional: bool = False) -> dict:
    """执行清理。返回明细；任何异常都体现在 `errors` 里，不往外抛。

    流程：拍保护指纹 → 逐个删 → 复核指纹。指纹不一致时**明确报错**，
    因为那意味着动到了不该动的东西。
    """
    before_fp = _fingerprint()

    removed: list[dict] = []
    errors: list[str] = []
    freed = 0

    for t in clean_targets():
        if t.optional and not include_optional:
            continue
        try:
            _guard(t.path)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not t.path.exists():
            continue
        size, count = _size_of(t.path)
        try:
            if t.path.is_file():
                t.path.unlink()
            else:
                shutil.rmtree(t.path, ignore_errors=False)
        except OSError as exc:
            # 文件被占用（界面窗口还开着）是预期内的，给一句人话提示
            errors.append(f"{t.path.name} 没删干净（{type(exc).__name__}）："
                          "界面窗口可能还开着，关掉它再试一次")
            continue
        if t.path.exists():
            left, _ = _size_of(t.path)
            errors.append(f"{t.path.name} 没删干净（还剩 {_mb(left)} MB）："
                          "界面窗口可能还开着，关掉它再试一次")
            continue
        freed += size
        removed.append({
            "path": str(t.path.relative_to(config.ROOT)),
            "size_mb": _mb(size),
            "files": count,
        })

    after_fp = _fingerprint()
    damaged = [p for p in before_fp if before_fp[p] != after_fp.get(p)]
    if damaged:
        # 走到这里说明保护清单被破坏了 —— 大声报出来，别装作没事
        errors.append("⚠️ 清理动到了受保护的内容，请立刻检查：" + "、".join(damaged))

    return {
        "removed": removed,
        "freed_mb": _mb(freed),
        "errors": errors,
        "protected_ok": not damaged,
    }

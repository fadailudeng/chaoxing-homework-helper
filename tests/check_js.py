"""检查 web/*.html 里内联 JS 的语法（node --check）。

为什么单独做一个：
    这几个页面是纯原生 JS 写在 HTML 里的，Python 单测覆盖不到。
    语法错了整页白屏，而且只有打开界面才会发现 —— 这个检查几秒钟就能兜住。
    已经在开发中靠它抓到过：函数定义顺序错（在定义之前调用）、模板字符串引号错配等。

跑法：python tests/check_js.py
（找不到 node 就跳过，不算失败 —— 它只是便捷检查，不是硬依赖）
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
sys.stdout.reconfigure(encoding="utf-8")


def find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    for guess in (r"D:\node.js\node.exe", r"C:\Program Files\nodejs\node.exe"):
        if Path(guess).exists():
            return guess
    return None


def main() -> int:
    node = find_node()
    if not node:
        print("[SKIP] 找不到 node，跳过 JS 语法检查（不影响其它测试）")
        return 0
    print("node:", node, flush=True)

    # 临时文件放系统临时目录，别往项目目录里拉屎
    tmp = Path(tempfile.gettempdir()) / "_xxt_js_check.js"
    ok = True
    checked = 0
    try:
        for html in sorted(WEB.glob("*.html")):
            text = html.read_text(encoding="utf-8", errors="replace")
            for i, block in enumerate(re.findall(r"<script>(.*?)</script>", text, re.S), 1):
                tmp.write_text(block, encoding="utf-8")
                r = subprocess.run([node, "--check", str(tmp)],
                                   capture_output=True, text=True)
                good = r.returncode == 0
                ok = ok and good
                checked += 1
                print(f"[{'PASS' if good else 'FAIL'}] {html.name} script#{i} ({len(block)} 字符)")
                if not good:
                    print(r.stderr[:800])
    finally:
        tmp.unlink(missing_ok=True)

    print()
    print(f"检查了 {checked} 段内联 JS —— " + ("全部通过" if ok else "存在语法错误"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

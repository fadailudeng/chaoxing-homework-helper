"""清理缓存的命令行入口 —— 专供 `清理缓存.bat` 调用。

为什么不直接在 bat 里写 `python -c "..."`：`-c` 里的引号在 cmd.exe 下很容易
被吃掉（尤其路径含空格时）。一个独立脚本文件最省事，也能单独手动跑：

    python src/cleanup_cli.py survey            # 只看会清什么
    python src/cleanup_cli.py survey --optional # 连调试残留一起看
    python src/cleanup_cli.py run               # 执行（安全档）
    python src/cleanup_cli.py run --optional    # 执行（连调试残留）

退出码：0 = 成功；1 = 有东西没删干净或保护清单异常（bat 会照样继续重开界面，
但日志里能看到）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

import cleanup  # noqa: E402


def _print_survey(include_optional: bool) -> dict:
    info = cleanup.survey(include_optional=include_optional)
    if not info["items"]:
        print("        nothing to clean (already tidy).")
    for it in info["items"]:
        print(f"        {it['size_mb']:>8.1f} MB  {it['files']:>5} files  {it['path']}")
    print(f"        {'-' * 46}")
    print(f"        {info['total_mb']:>8.1f} MB  total")
    return info


def _print_protected() -> None:
    print("        keeping (never touched):")
    for item in cleanup.survey()["protected"]:
        mark = "ok " if item["exists"] else "-- "
        print(f"          [{mark}] {item['path']}  ({item['label']})")


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else "survey"
    include_optional = "--optional" in argv

    if action == "survey":
        _print_survey(include_optional)
        _print_protected()
        return 0

    if action == "run":
        before = _print_survey(include_optional)
        result = cleanup.run(include_optional=include_optional)
        print(f"        freed: {result['freed_mb']} MB")
        for err in result["errors"]:
            print(f"        ! {err}")
        if not result["protected_ok"]:
            print("        !! PROTECTED CONTENT CHANGED -- check the message above")
            return 1
        if result["errors"]:
            return 1
        # 清理后复核一次：保护清单里的东西必须原封不动
        _print_protected()
        return 0
    if action == "protected":
        _print_protected()
        return 0

    print(f"unknown action: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

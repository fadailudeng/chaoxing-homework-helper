"""学习通作业助手 —— 桌面入口。

双击桌面图标运行的就是这个：启动本地界面服务，并用 Edge 应用窗口打开界面。

用 pythonw.exe 运行（不弹控制台黑窗口），所以出错信息走「界面 + data/app.log」，
而不是靠黑窗口里的报错 —— 这也是为什么这里要把 stdout 重定向到日志文件。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config  # noqa: E402
import server  # noqa: E402


def _redirect_output() -> None:
    """pythonw 下 sys.stdout/stderr 是 None，直接 print 会抛异常 —— 重定向到日志文件。"""
    if sys.stdout is not None and sys.stderr is not None:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        config.ensure_dirs()
        handle = open(config.DATA_DIR / "app.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = handle
        sys.stderr = handle
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    _redirect_output()
    try:
        server.serve()
    except Exception as exc:  # noqa: BLE001
        try:
            print(f"启动失败：{type(exc).__name__}: {exc}", flush=True)
        except Exception:  # noqa: BLE001
            pass
        # 服务起不来时退一步：至少把上次生成的看板打开给你看
        try:
            import os  # noqa: PLC0415

            if config.DASHBOARD_HTML.exists():
                os.startfile(str(config.DASHBOARD_HTML))  # noqa: S606
        except Exception:  # noqa: BLE001
            pass
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

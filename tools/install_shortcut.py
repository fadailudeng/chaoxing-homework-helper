"""在桌面创建带校徽图标的快捷方式（指向 pythonw + src/app.py，不弹黑窗口）。

常驻脚本，换机器 / 重装 / 想换名字时重跑即可：
    python tools/install_shortcut.py
    python tools/install_shortcut.py --name "学习通作业助手"

为什么用 -EncodedCommand 调 PowerShell：
本机 Git Bash 往原生程序传中文参数会被按 GBK 拆坏，
而 -EncodedCommand 走的是 UTF-16LE + Base64，完全绕开编码问题。
"""
from __future__ import annotations

import argparse
import base64
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_PY = ROOT / "src" / "app.py"
ICON = ROOT / "assets" / "app.ico"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def pythonw() -> Path:
    """和当前解释器同目录的 pythonw.exe（无控制台窗口的版本）。"""
    cand = Path(sys.executable).with_name("pythonw.exe")
    return cand if cand.exists() else Path(sys.executable)


def build_ps(name: str, target: str, arguments: str, workdir: str, icon: str, desc: str) -> str:
    return (
        "$ErrorActionPreference='Stop'\n"
        "$ws = New-Object -ComObject WScript.Shell\n"
        "$desk = [Environment]::GetFolderPath('Desktop')\n"
        f"$path = Join-Path $desk '{name}.lnk'\n"
        "$lnk = $ws.CreateShortcut($path)\n"
        f"$lnk.TargetPath = '{target}'\n"
        f"$lnk.Arguments = '{arguments}'\n"
        f"$lnk.WorkingDirectory = '{workdir}'\n"
        f"$lnk.IconLocation = '{icon}'\n"
        f"$lnk.Description = '{desc}'\n"
        "$lnk.Save()\n"
        "Write-Output ('OK ' + $path)\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="创建桌面快捷方式")
    ap.add_argument("--name", default="学习通作业助手", help="快捷方式名称")
    args = ap.parse_args()

    if not APP_PY.exists():
        print(f"找不到入口文件：{APP_PY}")
        return 1
    if not ICON.exists():
        print(f"⚠ 找不到图标 {ICON}，快捷方式会用默认图标。先跑 assets/make_icon.py 生成。")

    target = str(pythonw())
    script = build_ps(
        name=args.name,
        target=target,
        arguments=f'"{APP_PY}"',
        workdir=str(ROOT),
        icon=str(ICON),
        desc="一键扫描学习通所有课程的作业",
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")

    proc = subprocess.run(  # noqa: S603
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        capture_output=True,
    )
    out = (proc.stdout or b"").decode("utf-8", "replace").strip()
    err = (proc.stderr or b"").decode("utf-8", "replace").strip()

    print(f"目标：{target}")
    print(f"参数：\"{APP_PY}\"")
    print(f"图标：{ICON}")
    if out:
        print(f"结果：{out}")
    if err:
        print(f"stderr：{err}")
    return 0 if "OK" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())

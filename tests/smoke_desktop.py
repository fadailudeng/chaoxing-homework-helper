"""桌面入口冒烟测试：真的启动一次，确认界面窗口和服务都起来了，然后收拾干净。

会短暂弹出界面窗口（几秒），跑完自动关闭。
跑法：python tests/smoke_desktop.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import config  # noqa: E402
import server  # noqa: E402

ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""), flush=True)


def edge_pids() -> list[str]:
    """找出用着我们界面专用 profile 的 Edge 进程（不会碰到你平时开着的 Edge）。"""
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{config.WEBVIEW_PROFILE_DIR.name}*' }} | "
        "Select-Object -ExpandProperty ProcessId"
    )
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True, timeout=30,
        ).stdout.decode("utf-8", "replace")
        return [line.strip() for line in out.splitlines() if line.strip().isdigit()]
    except Exception:  # noqa: BLE001
        return []


def kill(pids: list[str]) -> None:
    if not pids:
        return
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command",
         "Stop-Process -Id " + ",".join(pids) + " -Force -ErrorAction SilentlyContinue"],
        capture_output=True, timeout=30,
    )


def main() -> int:
    config.ensure_dirs()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    app_py = Path(__file__).resolve().parent.parent / "src" / "app.py"

    log_path = config.DATA_DIR / "app.log"
    before = log_path.stat().st_size if log_path.exists() else 0

    print(f"启动：{pythonw.name} {app_py.name}", flush=True)
    proc = subprocess.Popen([str(pythonw), str(app_py)], cwd=str(app_py.parent.parent))

    url = f"http://127.0.0.1:{server.DEFAULT_PORT}/api/state"
    state = None
    for _ in range(30):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                state = json.loads(resp.read().decode("utf-8"))
            break
        except Exception:  # noqa: BLE001
            continue

    check("服务在固定端口上起来了", state is not None, url)
    if state:
        check("状态接口结构正常", "phase" in state and "log" in state,
              f"phase={state.get('phase')}")

    time.sleep(2)
    pids = edge_pids()
    check("Edge 应用窗口已打开", len(pids) > 0, f"pids={pids[:3]}{'...' if len(pids) > 3 else ''}")

    # 收拾干净
    try:
        proc.terminate()
        proc.wait(timeout=8)
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
    kill(edge_pids())
    time.sleep(1)
    check("界面窗口已关闭", len(edge_pids()) == 0)

    if log_path.exists():
        new = log_path.read_text(encoding="utf-8", errors="replace")[before:]
        bad = [ln for ln in new.splitlines() if "Traceback" in ln or "Error" in ln]
        check("启动日志无报错", not bad, (bad[0] if bad else new.strip().splitlines()[-1] if new.strip() else "（无输出）"))

    print("\n" + ("全部通过" if ok else "存在失败项"), flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""「代码更新后自动接管」的回归测试。

为什么需要它（2026-10-02 老大提的问题）：
    界面窗口里的**网页**每次从磁盘读，改了立刻可见；但**服务端代码**是进程启动时
    载入内存的。原来的 serve() 一发现端口上有服务就直接复用 ——
    于是「关掉窗口再双击图标」永远是旧代码，每次都得手动跑「重启界面.bat」。

现在的行为：
    app.py 启动时问旧进程「你加载的代码指纹是多少」，
    不一样（磁盘上更新了）→ 让旧进程自己退出，用新代码重新起服务；
    一样 → 复用（避免重复双击开出两个界面）。

跑法：python tests/test_takeover.py
（会在一个随机空闲端口上短暂起一个子进程当"旧服务"，跑完自动收拾）
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8")

import server  # noqa: E402

ok = True


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok
    ok = ok and cond
    print(f"[{'PASS' if cond else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""), flush=True)


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    port = free_port()
    inline = (
        f"import sys; sys.path.insert(0, {str(ROOT / 'src')!r}); "
        f"import server; server.serve({port}, open_window=False, block=True)"
    )

    # ── 纯逻辑部分（不需要子进程）────────────────────────
    check("code_fingerprint 是 16 位十六进制", len(server._FINGERPRINT) == 16,
          server._FINGERPRINT)
    check("同指纹 → 不接管（复用旧窗口）",
          server._should_take_over({"fingerprint": server._FINGERPRINT}) is False)
    check("指纹不同 → 接管（换成新代码）",
          server._should_take_over({"fingerprint": "0" * 16}) is True)
    check("指纹不同但旧进程在跑任务 → 不接管（免得结果丢）",
          server._should_take_over({"fingerprint": "0" * 16, "running": True}) is False)
    check("没有旧进程 → 不接管", server._should_take_over(None) is False)

    # ── 真起一个"旧服务"子进程 ────────────────────────────
    proc = subprocess.Popen(
        [sys.executable, "-c", inline],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
    )
    info = None
    for _ in range(60):
        time.sleep(0.5)
        info = server._running_info(port)
        if info:
            break
    if not info:
        check("旧服务起来了", False, "起不来，后面的测不了")
        proc.kill()
        return 1
    check("旧服务起来了，并自报代码指纹", True, f"fingerprint={info.get('fingerprint')}")
    check("指纹一致 → 判定复用", server._should_take_over(info) is False)

    # ── 模拟"磁盘上的代码更新了" ─────────────────────────
    real = server._FINGERPRINT
    server._FINGERPRINT = "f" * 16
    check("指纹变了 → 判定接管", server._should_take_over(info) is True)

    t0 = time.time()
    stopped = server._stop_running(port)
    check("旧进程自己退出、并让出端口", stopped, f"耗时 {time.time() - t0:.1f} 秒")
    # ⚠️ 这里必须等，不能发完 shutdown 就立刻 poll：
    # _die_soon() 里先 sleep(0.5) 把 HTTP 响应写完，才 os._exit(0)，
    # 而 _stop_running() 一等到端口释放就返回了 —— 立刻 poll 必然拿到 None。
    for _ in range(40):
        if proc.poll() is not None:
            break
        time.sleep(0.1)
    check("旧进程确实退出了", proc.poll() is not None, f"退出码 {proc.poll()}")
    check("端口已释放", server._already_running(port) is False)
    server._FINGERPRINT = real

    if proc.poll() is None:
        proc.kill()

    print()
    print("全部通过" if ok else "存在失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

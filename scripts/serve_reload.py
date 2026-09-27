"""带自动重启的后端启动器 —— 改完源码不用手动重启服务。

**为什么需要它：**
  uvicorn 只在启动时加载一次源码。改了 .py 但没重启，进程里还是老模块，
  **而且不报错** —— 表现就是「改了跟没改一样」。这个坑在开发期反复出现，
  每次都要人工发现、人工重启，非常费神。

**为什么不用 `uvicorn --reload`：**
  它的热加载基于 multiprocessing，在 Windows 上要创建命名管道；受限环境里
  会直接 `PermissionError: [WinError 5] 拒绝访问`，服务根本起不来（实测）。
  所以这里用最朴素、哪都能跑的办法：

    用 subprocess 起 uvicorn（stdio 直接继承），
    每秒看一眼 src/aihoop/*.py 的修改时间，变了就杀掉重启。

  不依赖任何花哨机制，也不会把服务输出吃掉。

用法：
    python scripts/serve_reload.py [端口]        # 默认 8000
    python scripts/serve_reload.py 8000 --no-reload   # 关掉自动重启
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
WATCH_DIR = SRC / "aihoop"
POLL_S = 1.0


def snapshot() -> dict:
    """当前源码指纹：每个 .py 的修改时间。"""
    out = {}
    for p in WATCH_DIR.glob("*.py"):
        try:
            out[str(p)] = p.stat().st_mtime
        except OSError:
            pass
    return out


def settle(seconds: float = 1.0, timeout: float = 8.0) -> dict:
    """等源码修改时间稳定下来再重启。

    我一次改动常常连着碰好几个文件，不 debounce 就会重启好几次，
    每次都有 1~3 秒接口不可用 —— 用户正好在那一下点上传就会失败。
    """
    prev = snapshot()
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(seconds)
        cur = snapshot()
        if cur == prev:
            return cur
        prev = cur
    return prev


def jobs_running(port: str) -> bool:
    """后端上还有没有正在跑/排队的任务。

    有的话**先别重启** —— 重启会直接把它们杀掉，用户跑了几十分钟的分析就没了。
    """
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/jobs", timeout=2.0) as r:
            rows = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return False
    return any(str(j.get("status")) in ("queued", "running") for j in rows)


def stop(proc: subprocess.Popen, timeout: float = 8.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except Exception:  # noqa: BLE001
        proc.kill()


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    autoreload = "--no-reload" not in argv
    argv = [a for a in argv if a != "--no-reload"]
    port = argv[0] if argv else "8000"

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])
    env.setdefault("PYTHONIOENCODING", "utf-8")
    cmd = [sys.executable, "-m", "aihoop.cli", "serve", "--port", str(port)]

    print("=" * 60)
    print("  AI 篮球分析软件 · 后端")
    print(f"  接口文档 : http://127.0.0.1:{port}/docs")
    print(f"  健康检查 : http://127.0.0.1:{port}/api/health")
    print(f"  自动重启 : {'开（改源码后约 2 秒自动生效）' if autoreload else '关'}")
    print("=" * 60)
    print()

    while True:
        # stdio 直接继承：既保证控制台能看到 uvicorn 日志，
        # 也避开受限环境对管道/命名管道的限制。
        proc = subprocess.Popen(cmd, cwd=str(ROOT), env=env)
        before = snapshot()
        restart = False
        try:
            while proc.poll() is None:
                time.sleep(POLL_S)
                if autoreload and snapshot() != before:
                    restart = True
                    break
        except KeyboardInterrupt:
            stop(proc)
            print("\n[stop] 收到 Ctrl+C，已停止后端")
            return 0

        stop(proc)
        if not restart:
            # 进程自己退出了（端口被占、启动报错等），不要无限重启
            return proc.returncode or 0
        # 改动可能还没停（我常连着改好几个文件），等它稳定
        settle()
        # 有任务在跑就等它跑完再重启 —— 别把用户几十分钟的分析杀掉
        waited = 0.0
        while jobs_running(port) and waited < 1800:
            if waited == 0.0:
                print("[autoreload] 有任务正在运行，等它跑完再重启…")
            time.sleep(5)
            waited += 5
        print("\n[autoreload] 检测到源码变更，正在重启后端 …")
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())

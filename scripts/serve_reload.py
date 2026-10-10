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
    每秒看一眼 src/aihoop/**/*.py 的修改时间，变了就杀掉重启。

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
    for p in WATCH_DIR.rglob("*.py"):
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


_WARNED = set()


def _warn_once(key: str, msg: str) -> None:
    """同一件事只喊一次：轮询是每秒一次，不去重就会把控制台刷满。"""
    if key in _WARNED:
        return
    _WARNED.add(key)
    print(msg)


def ensure_internal_token(env: dict) -> str:
    """给「这个启动器」和「它起的后端子进程」一个共用的内部令牌。

    **为什么必须要有：** 登录网关上线后，未登录访问 /api/jobs 返回 401，
    而下面的 jobs_running() 正是靠这个接口判断"现在能不能安全重启"。
    于是源码一改，它每次都读不到任务状态 → 按"状态未知"保守处理 → **自动重启
    被无限推迟，而且一个字都不提示**。现象就是"改完源码等 2 秒什么都没发生"，
    用户完全看不出是网关把自动重启掐死的（实测踩到，这版修掉）。

    令牌只放在进程环境里（不落盘），且必须**回环地址 + 令牌都对**才豁免，
    所以不会把登录绕成公开接口（见 src/aihoop/auth.py 的 internal_ok）。
    """
    import secrets
    tok = str(env.get("AIHOOP_INTERNAL_TOKEN") or "").strip()
    if not tok:
        tok = secrets.token_urlsafe(24)
        env["AIHOOP_INTERNAL_TOKEN"] = tok
        print("[token] 已生成本次运行的内部令牌：自动重启靠它读 /api/jobs"
              "（仅本机回环 + 该令牌可免登录，不写进任何文件）")
    return tok


def jobs_running(port: str, token: str = "") -> bool:
    """后端上还有没有正在跑/排队的任务。

    有的话**先别重启** —— 重启会直接把它们杀掉，用户跑了几十分钟的分析就没了。
    """
    import json
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/jobs")
    if token:
        req.add_header("X-Internal-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=2.0) as r:
            rows = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:  # noqa: PERF203
        if e.code in (401, 403):
            # 「没登录」不等于「有任务在跑」，但这种情况下我们确实判断不了，
            # 所以保守不重启 —— 关键是**说出来**，不能让它静默失效。
            _warn_once("jobs-auth",
                       f"[jobs] 读 /api/jobs 被拒（HTTP {e.code}）：无法确认任务状态，"
                       f"本次不自动重启。想恢复自动重启，请从「启动后端.bat」"
                       f"（它会给后端和本启动器配同一个内部令牌）启动。")
        return True
    except Exception:  # noqa: BLE001
        return True  # 状态未知时不自动杀进程；宁可延后重载
    return any(str(j.get("status")) in ("queued", "running") for j in rows)


def stop(proc: subprocess.Popen, timeout: float = 8.0) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except Exception:  # noqa: BLE001
        proc.kill()


def pids_listening(port: str) -> list:
    """谁在监听这个端口（返回 PID 列表）。

    为什么要自己查：这个启动器用子进程跑 uvicorn，**关掉控制台窗口时子进程
    常常不跟着死**，变成孤儿继续占着端口。再启动一次就会失败（端口被占），
    窗口一闪而过 —— 用户看到的就是"关掉窗口也重启不了"（实测踩到）。
    """
    pids = []
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, errors="replace",
                             timeout=15).stdout
    except Exception:  # noqa: BLE001
        return pids
    needle = ":" + str(port)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].upper() == "TCP" and "LISTENING" in parts[3].upper():
            if parts[1].endswith(needle):
                try:
                    pid = int(parts[4])
                except ValueError:
                    continue
                if pid and pid not in pids:
                    pids.append(pid)
    return pids


def free_port(port: str) -> bool:
    """把占着端口的旧进程清掉。返回"现在端口是空的吗"。

    只在**确实没人监听**时才返回 True —— 不然我们还是照常启动，
    让 uvicorn 自己报"端口被占用"，用户能看到完整报错。
    """
    pids = pids_listening(port)
    if not pids:
        return True
    me = os.getpid()
    pids = [p for p in pids if p != me]
    print(f"[port] 端口 {port} 被 PID {pids} 占着 —— 先结束它（这是上次没退干净的旧后端）")
    for pid in pids:
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=15)
        except Exception as e:  # noqa: BLE001
            print(f"[port] 结束 PID {pid} 失败：{type(e).__name__}: {e}")
    for _ in range(10):                      # 等它把端口放开，最多 5 秒
        time.sleep(0.5)
        if not pids_listening(port):
            print(f"[port] 端口 {port} 已释放")
            return True
    left = pids_listening(port)
    print(f"[port] 端口 {port} 仍被 {left} 占着 —— 请用管理员身份运行一次，"
          f"或在任务管理器里结束那个 python.exe")
    return False


def cleanup_orphans(port: str) -> None:
    """退出时尽力把还占着端口的子进程清掉（Ctrl+C / 窗口关闭都走这里）。"""
    for pid in pids_listening(port):
        if pid == os.getpid():
            continue
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True, timeout=8)
        except Exception:  # noqa: BLE001
            pass


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    autoreload = "--no-reload" not in argv
    kill_port = "--kill-port" in argv
    argv = [a for a in argv if a not in ("--no-reload", "--kill-port")]
    port = argv[0] if argv else "8000"

    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(SRC)] + [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p])
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # 内部令牌必须在起子进程**之前**定好：后端进程和本启动器要用同一个值，
    # 否则下面的任务检查会被登录网关挡掉（详见 ensure_internal_token）。
    token = ensure_internal_token(env)
    cmd = [sys.executable, "-m", "aihoop.cli", "serve", "--port", str(port)]

    print("=" * 60)
    print("  AI 篮球分析软件 · 后端")
    print(f"  接口文档 : http://127.0.0.1:{port}/docs")
    print(f"  健康检查 : http://127.0.0.1:{port}/api/health")
    print(f"  自动重启 : {'开（改源码后约 2 秒自动生效）' if autoreload else '关'}")
    print("=" * 60)
    print()

    # 启动前先看一眼端口：上次没退干净的旧后端会一直占着它，
    # 导致新进程起不来、窗口一闪而过（实测踩到）。默认只报告，
    # 加 --kill-port（或 重启后端.bat）才动手清。
    if kill_port:
        free_port(port)
    else:
        busy = pids_listening(port)
        if busy:
            print(f"[port] 提醒：端口 {port} 已被 PID {busy} 占着。")
            print("[port] 如果是上次没退干净的旧后端，用「重启后端.bat」"
                  "（或加 --kill-port）可以自动清掉。")
            print()

    try:
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
                        # 必须在停止子进程之前等任务结束；不能先杀服务再查任务。
                        if jobs_running(port, token):
                            time.sleep(4)
                            continue
                        settle()
                        if jobs_running(port, token):
                            continue
                        restart = True
                        break
            except KeyboardInterrupt:
                stop(proc)
                cleanup_orphans(port)
                print("\n[stop] 收到 Ctrl+C，已停止后端")
                return 0

            stop(proc)
            if not restart:
                # 进程自己退出了（端口被占、启动报错等），不要无限重启
                return proc.returncode or 0
            print("\n[autoreload] 检测到源码变更，正在重启后端 …")
            time.sleep(0.5)
    finally:
        # 窗口被关 / 进程被杀时也尽量别留孤儿（子进程还占着端口就白重启了）
        cleanup_orphans(port)



if __name__ == "__main__":
    raise SystemExit(main())

"""一键跑完所有自检 —— 答辩前每次改动后跑这个。

包含：
  1. Python 端到端自检（tests/test_plan_a.py，11 项，零第三方依赖）
  1b.战术层自检（tests/test_plan_b.py，16 项，零第三方依赖）
  2. 实施手册的 Python 代码块可编译性（scripts/verify_doc_code.py）
  3. 实施手册引用的文件/函数是否存在（scripts/verify_doc_refs.py）
  4. 实施手册里的 CLI 调用是否与 argparse 一致（scripts/verify_doc_cli.py）
  5. 前端口径与功能自检（node web/_validate.js、web/_test.js，有 node 才跑）
  6. API 集成测试（tests/test_api.py，装了 fastapi 才跑）

用法：
    python scripts/check_all.py
    python scripts/check_all.py --quick     # 跳过需要第三方依赖的项

Windows 上如果 PowerShell 的执行策略拦住了 .ps1，用这个 .py 入口最省事。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
ENV = {
    "PYTHONPATH": str(ROOT / "src"),
    # 关键：子进程强制 UTF-8 输出。否则 Windows 上子进程按 GBK 写管道，
    # 中文会变成乱码，甚至产生无法回写的替换字符（UnicodeEncodeError）。
    "PYTHONIOENCODING": "utf-8",
}


def _safe_print(text: str) -> None:
    """按 UTF-8 直接写字节输出，绕开 Windows 控制台/管道代码页的限制。

    Windows 上 sys.stdout 可能是 GBK，遇到无法编码的字符（如 U+FFFD）
    会抛 UnicodeEncodeError 把整个脚本打断 —— 这里显式用 UTF-8 写 buffer，
    并在失败时退回 ASCII 以防彻底崩掉。
    """
    buf = getattr(sys.stdout, "buffer", None)
    if buf is None:
        print(text)
        return
    try:
        buf.write((text + "\n").encode("utf-8", errors="replace"))
        buf.flush()
    except Exception:  # noqa: BLE001
        print(text.encode("ascii", errors="replace").decode("ascii"))


def run(label: str, cmd: list[str], required: bool = True) -> bool:
    _safe_print(f"\n{'=' * 68}\n{label}\n{'=' * 68}")
    try:
        import os
        env = dict(os.environ)
        env.update(ENV)
        p = subprocess.run(cmd, cwd=str(ROOT), env=env,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900)
    except Exception as e:  # noqa: BLE001
        _safe_print(f"  [ERR] 无法执行：{type(e).__name__}: {e}")
        return not required
    tail = (p.stdout or "").strip().splitlines()
    for line in tail[-14:]:
        _safe_print("  " + line)
    if p.returncode != 0:
        err = (p.stderr or "").strip().splitlines()
        if err:
            _safe_print("  --- stderr ---")
            for line in err[-8:]:
                _safe_print("  " + line)
        _safe_print(f"  [FAIL] 退出码 {p.returncode}")
        return False
    _safe_print("  [OK]")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true",
                    help="跳过需要第三方依赖的项（API 测试）")
    args = ap.parse_args(argv)

    results: list[tuple[str, bool]] = []

    results.append(("Python 端到端自检（11 项）", run(
        "1/9 Python 端到端自检 tests/test_plan_a.py",
        [PY, "-B", "tests/test_plan_a.py"])))

    results.append(("比分牌 + 球/篮筐自检（50 项）", run(
        "2/9 比分牌识别 + 证据融合自检 tests/test_scoreboard.py",
        [PY, "-B", "tests/test_scoreboard.py"])))

    results.append(("篮下判进球自检（17 项）", run(
        "2b/9 篮下判进球（不靠比分牌/球检测器）自检 tests/test_hoopsight.py",
        [PY, "-B", "tests/test_hoopsight.py"])))

    results.append(("进球分队自检（16 项）", run(
        "2c/9 「这一球是哪一队进的」自检 tests/test_baskets.py",
        [PY, "-B", "tests/test_baskets.py"])))

    results.append(("战术层自检（16 项）", run(
        "3/9 战术层自检 tests/test_plan_b.py",
        [PY, "-B", "tests/test_plan_b.py"])))

    results.append(("手册代码块可编译", run(
        "4/9 手册 Python 代码块编译检查",
        [PY, "-B", "scripts/verify_doc_code.py"])))

    results.append(("手册引用有效", run(
        "5/9 手册引用的文件/函数对账",
        [PY, "-B", "scripts/verify_doc_refs.py"])))

    results.append(("手册 CLI 调用有效", run(
        "6/9 手册 CLI 调用 vs argparse",
        [PY, "-B", "scripts/verify_doc_cli.py"])))

    results.append(("PowerShell 脚本带 BOM", run(
        "7/9 .ps1 编码检查（PowerShell 5.1 兼容）",
        [PY, "-B", "scripts/fix_ps1_bom.py", "--check"])))

    node = shutil.which("node")
    if node:
        ok1 = run("8/9 前端功能自检 web/_test.js", [node, "web/_test.js"])
        ok2 = run("8/9 前端口径校验 web/_validate.js", [node, "web/_validate.js"])
        results.append(("前端自检", ok1 and ok2))
    else:
        _safe_print("\n[skip] 未找到 node，跳过前端自检（不影响后端功能）")

    if args.quick:
        _safe_print("\n[skip] --quick：跳过 API 集成测试")
    else:
        try:
            import fastapi  # noqa: F401
            import httpx    # noqa: F401
            results.append(("API 集成测试（3 项）", run(
                "9/9 API 集成测试 tests/test_api.py",
                [PY, "-B", "tests/test_api.py"])))
        except ImportError:
            _safe_print("\n[skip] 未安装 fastapi/httpx，跳过 API 测试"
                        "（pip install -r requirements.txt 后可跑）")

    _safe_print(f"\n{'=' * 68}\n汇总\n{'=' * 68}")
    for name, ok in results:
        _safe_print(f"  {'[OK]  ' if ok else '[FAIL]'} {name}")
    bad = sum(1 for _, ok in results if not ok)
    _safe_print(f"\n{'全部通过' if bad == 0 else f'{bad} 项失败'}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

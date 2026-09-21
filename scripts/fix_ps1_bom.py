"""确保所有 .ps1 脚本都是「UTF-8 带 BOM」。

为什么需要（真实踩过的坑）：
    Windows PowerShell 5.1 读取**无 BOM 的 UTF-8** .ps1 时，会按系统 ANSI(GBK)
    解码。中文注释因此乱码，某些字符（如全角引号、破折号）会吞掉换行，
    把下一行代码变成注释的一部分 —— 脚本表面上还在跑，行为却完全不对，
    报错位置也指向莫名其妙的地方，极难排查。

    本工程曾因此让 sync_demo.ps1 里的 `$hlSrc = ...` 被注释掉，
    触发 Test-Path 参数为 null 的诡异错误。

用法（在 aihoopanalyst 目录下）：
    python scripts/fix_ps1_bom.py            # 检查并修复
    python scripts/fix_ps1_bom.py --check    # 只检查，不修改（非零退出表示有问题）
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"

# 扫描范围：仓库里所有 .ps1（含根目录的启动器）
PATTERNS = ["scripts/*.ps1", "*.ps1"]


def targets() -> list[Path]:
    out: list[Path] = []
    for pat in PATTERNS:
        out.extend(sorted(ROOT.glob(pat)))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不修改")
    args = ap.parse_args(argv)

    files = targets()
    if not files:
        print("没有找到任何 .ps1 文件")
        return 0

    need = []
    for p in files:
        raw = p.read_bytes()
        if raw.startswith(BOM):
            print(f"  [OK]   {p.relative_to(ROOT)}")
            continue
        # 先确认内容是合法 UTF-8，否则加 BOM 也救不了
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            print(f"  [BAD]  {p.relative_to(ROOT)} 不是合法 UTF-8：{e}")
            need.append(p)
            continue
        if args.check:
            print(f"  [MISS] {p.relative_to(ROOT)} 缺少 BOM")
            need.append(p)
            continue
        p.write_bytes(BOM + text.encode("utf-8"))
        print(f"  [FIX]  {p.relative_to(ROOT)} 已补上 BOM")

    print()
    if need and args.check:
        print(f"{len(need)} 个 .ps1 缺少 BOM —— 在 Windows PowerShell 5.1 下会乱码。")
        print("运行 `python scripts/fix_ps1_bom.py` 修复。")
        return 1
    if need:
        print(f"{len(need)} 个文件需要人工检查（不是合法 UTF-8）。")
        return 1
    print(f"全部 {len(files)} 个 .ps1 都带 BOM，PowerShell 5.1 可安全读取。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

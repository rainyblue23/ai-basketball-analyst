# -*- coding: utf-8 -*-
"""校验人工标注的真值文件：**在写进方案之前**把格式错误挑出来。

为什么要有它（用户 2026-10-11：「我来按清单标」）：
    真值一旦标错，后面算出来的指标是假数字 —— 而假数字比没有数字更糟。
    标注人最不该花的力气是"标了两个小时，导入时才发现字段名不对"。
    所以先给一份**模板**（`eval/ground_truth/templates/`），再用这个脚本自检：
    字段、类型、取值范围、时间是否落在片段内、sample id 对不对得上测试集。
    它**只读**，绝不改标注文件。

用法::

    python scripts/check_truth_files.py                       # 检查 eval/ground_truth/ 下所有真值
    python scripts/check_truth_files.py eval/ground_truth/jersey_split1.json
    python scripts/check_truth_files.py --quiet               # 只打印结论

退出码：0 = 没有硬错误（可以有警告）；1 = 有硬错误（这种文件不能直接拿来算指标）。
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "eval" / "ground_truth"
DEFAULT_BASE = DEFAULT_DIR / "match_testset_20261011.json"

# 建议标注量（与 docs/需要人工标注的真值清单_2026-10-11.md 一致）
TARGETS = {
    "jersey": ("轨迹-号码对", 100),
    "tactics": ("回合", 30),
    "scoreboard": ("帧读数", 100),
    "shots": ("出手", 20),
}

TEAMS = {"home", "away"}


class Report:
    def __init__(self, path: Path):
        self.path = path
        self.errors: list = []
        self.warns: list = []
        self.notes: list = []

    def err(self, msg: str):
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warns.append(msg)

    def note(self, msg: str):
        self.notes.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _jersey_str(v):
    """号码的正常形式：None（不可读）或 '0'~'99' 字符串。数字也接受，统一成字符串。"""
    if v is None:
        return None, None
    if isinstance(v, bool):
        return None, "号码不能是布尔值"
    if isinstance(v, int):
        v = str(v)
    if not isinstance(v, str):
        return None, f"号码类型不对：{type(v).__name__}"
    s = v.strip()
    if not re.fullmatch(r"\d{1,2}", s):
        return None, f"号码必须是 0~99 的数字（现在 {v!r}）"
    return s, None


def detect_kind(data: dict) -> str:
    """按内容判断这是哪一类真值；判不出来就返回 'unknown'。"""
    if not isinstance(data, dict):
        return "unknown"
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        return "unknown"
    s0 = samples[0] if isinstance(samples[0], dict) else {}
    if "tracks" in s0:
        return "jersey"
    if "possessions" in s0:
        return "tactics"
    if "readings" in s0 or ("frames" in s0 and "score" in json.dumps(s0)[:400]):
        return "scoreboard"
    if "shots" in s0:
        return "shots"
    return "unknown"


def base_index(base_path: Path | None) -> dict:
    """测试集索引：sample id → {video, start_s, end_s, shots}。用来核对标注挂在对的片段上。"""
    if not base_path or not Path(base_path).exists():
        return {}
    d = json.loads(Path(base_path).read_text(encoding="utf-8"))
    out = {}
    for s in d.get("samples") or []:
        out[str(s.get("id"))] = s
    return out


def _check_sample_span(rep: Report, sid: str, base: dict, t: float, what: str) -> None:
    """时间必须落在该片段范围内（否则指标会把这段算成漏检）。"""
    if sid not in base:
        rep.err(f"{what}：sample id `{sid}` 不在测试集里（可用 id：{sorted(base) or '未知'}）")
        return
    a, b = base[sid].get("start_s"), base[sid].get("end_s")
    if _is_num(a) and _is_num(b) and not (a <= t <= b):
        rep.err(f"{what}：时间 {t} 不在片段 [{a}, {b}] 内（{sid}）")


def check_jersey(rep: Report, data: dict, base: dict) -> None:
    total = 0
    unreadable = 0
    for s in data.get("samples") or []:
        sid = str(s.get("id"))
        tracks = s.get("tracks")
        if not isinstance(tracks, list):
            rep.err(f"[{sid}] 缺少 tracks 列表")
            continue
        seen = set()
        for i, t in enumerate(tracks):
            if not isinstance(t, dict):
                rep.err(f"[{sid}] tracks[{i}] 不是对象")
                continue
            total += 1
            tid = t.get("track_id")
            if not isinstance(tid, int) or isinstance(tid, bool):
                rep.err(f"[{sid}] tracks[{i}] 的 track_id 必须是整数（引擎的轨迹号）")
            elif tid in seen:
                rep.err(f"[{sid}] track_id {tid} 重复出现（同一条轨迹只能标一次）")
            else:
                seen.add(tid)
            j, msg = _jersey_str(t.get("jersey"))
            if msg:
                rep.err(f"[{sid}] track_id={tid}：{msg}")
            readable = t.get("readable")
            if not isinstance(readable, bool):
                rep.err(f"[{sid}] track_id={tid} 的 readable 必须是 true/false（"
                        "「看不清」就写 false，不许猜号码）")
            else:
                if readable and j is None:
                    rep.err(f"[{sid}] track_id={tid}：readable=true 却没给号码")
                if (not readable) and j is not None:
                    rep.err(f"[{sid}] track_id={tid}：readable=false 却又给了号码 {j} —— 二者只能有一个")
                if not readable:
                    unreadable += 1
            team = t.get("team")
            if team is not None and team != "" and team not in TEAMS:
                rep.err(f"[{sid}] track_id={tid} 的 team 只能是 home/away/空（现在 {team!r}）")
            ev = t.get("evidence_s") or []
            if not isinstance(ev, list):
                rep.err(f"[{sid}] track_id={tid} 的 evidence_s 必须是数组")
            else:
                for x in ev:
                    if not _is_num(x):
                        rep.err(f"[{sid}] track_id={tid} 的 evidence_s 里有非数字：{x!r}")
                    else:
                        _check_sample_span(rep, sid, base, float(x), f"track_id={tid} evidence_s")
                if j is not None and not ev:
                    rep.warn(f"[{sid}] track_id={tid}：给了号码但没写 evidence_s（"
                             "事后无法复核你是在哪一秒看到的）")
    name, target = TARGETS["jersey"]
    rep.note(f"球衣号码：{total} 条{name}（其中不可读 {unreadable} 条）；建议 ≥{target} 条 —— "
             + ("够了" if total >= target else f"还差 {target - total} 条"))


def check_tactics(rep: Report, data: dict, base: dict) -> None:
    n_poss = n_pass = 0
    for s in data.get("samples") or []:
        sid = str(s.get("id"))
        poss = s.get("possessions")
        if not isinstance(poss, list):
            rep.err(f"[{sid}] 缺少 possessions 列表")
            continue
        last_end = None
        for i, p in enumerate(poss):
            if not isinstance(p, dict):
                rep.err(f"[{sid}] possessions[{i}] 不是对象")
                continue
            n_poss += 1
            a, b = p.get("start_s"), p.get("end_s")
            if not (_is_num(a) and _is_num(b)):
                rep.err(f"[{sid}] possessions[{i}] 的 start_s/end_s 必须是数字")
            elif not a < b:
                rep.err(f"[{sid}] possessions[{i}] start_s({a}) 必须小于 end_s({b})")
            else:
                _check_sample_span(rep, sid, base, float(a), f"possessions[{i}] start_s")
                _check_sample_span(rep, sid, base, float(b), f"possessions[{i}] end_s")
                if last_end is not None and a < last_end:
                    rep.warn(f"[{sid}] possessions[{i}] 与上一个回合时间重叠（{a} < {last_end}）")
                last_end = b
            if p.get("team") not in TEAMS:
                rep.err(f"[{sid}] possessions[{i}] 的 team 只能是 home/away（现在 {p.get('team')!r}）")
            passes = p.get("passes") or []
            if not isinstance(passes, list):
                rep.err(f"[{sid}] possessions[{i}] 的 passes 必须是数组")
                continue
            for j, q in enumerate(passes):
                if not isinstance(q, dict):
                    rep.err(f"[{sid}] possessions[{i}].passes[{j}] 不是对象")
                    continue
                n_pass += 1
                t = q.get("t")
                if not _is_num(t):
                    rep.err(f"[{sid}] possessions[{i}].passes[{j}] 的 t 必须是数字")
                else:
                    _check_sample_span(rep, sid, base, float(t), f"passes[{j}] t")
                    if _is_num(a) and _is_num(b) and not (a <= t <= b):
                        rep.err(f"[{sid}] possessions[{i}].passes[{j}] 的 t={t} 不在这个回合 [{a}, {b}] 内")
                for key in ("from_track", "to_track"):
                    if not isinstance(q.get(key), int) or isinstance(q.get(key), bool):
                        rep.err(f"[{sid}] possessions[{i}].passes[{j}] 的 {key} 必须是整数轨迹号")
                if isinstance(q.get("from_track"), int) and q.get("from_track") == q.get("to_track"):
                    rep.err(f"[{sid}] possessions[{i}].passes[{j}] 传给自己不算传球")
    name, target = TARGETS["tactics"]
    rep.note(f"战术层：{n_poss} 个回合、{n_pass} 次传球；建议 ≥{target} 个{name} —— "
             + ("够了" if n_poss >= target else f"还差 {target - n_poss} 个"))


def check_scoreboard(rep: Report, data: dict, base: dict) -> None:
    n = 0
    for s in data.get("samples") or []:
        sid = str(s.get("id"))
        readings = s.get("readings") or []
        if not isinstance(readings, list):
            rep.err(f"[{sid}] 缺少 readings 列表")
            continue
        prev = None
        for i, r in enumerate(readings):
            if not isinstance(r, dict):
                rep.err(f"[{sid}] readings[{i}] 不是对象")
                continue
            n += 1
            t = r.get("t")
            if not _is_num(t):
                rep.err(f"[{sid}] readings[{i}] 的 t 必须是数字")
            else:
                _check_sample_span(rep, sid, base, float(t), f"readings[{i}] t")
            for key in ("home", "away"):
                v = r.get(key)
                if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                    rep.err(f"[{sid}] readings[{i}] 的 {key} 必须是非负整数（认不出就整条不写）")
            if prev and all(isinstance(r.get(k), int) for k in ("home", "away")):
                if r["home"] < prev["home"] or r["away"] < prev["away"]:
                    rep.warn(f"[{sid}] readings[{i}] 的比分比上一条小（"
                             f"{prev['home']}:{prev['away']} → {r['home']}:{r['away']}）—— 若确实如此请在 note 里写清")
                prev = r
            elif all(isinstance(r.get(k), int) for k in ("home", "away")):
                prev = r
    name, target = TARGETS["scoreboard"]
    rep.note(f"比分牌：{n} 条{name}；建议 ≥{target} 条 —— " + ("够了" if n >= target else f"还差 {target - n} 条"))


def check_shots(rep: Report, data: dict, base: dict) -> None:
    """出手真值（事件层）：release_s / result / value / is_replay。

    它是 `eval_match_annotations.py` 直接吃的格式，所以字段名一个字都不能错。
    """
    total = 0
    incomplete = 0
    for s in data.get("samples") or []:
        sid = str(s.get("id"))
        shots = s.get("shots")
        if not isinstance(shots, list):
            rep.err(f"[{sid}] 缺少 shots 列表")
            continue
        if s.get("shots_complete") is not True:
            incomplete += 1
            rep.warn(f"[{sid}] shots_complete 不是 true —— 这一段还没标完（或忘了改）")
        if not s.get("video"):
            rep.err(f"[{sid}] 缺少 video 路径")
        elif not Path(str(s["video"])).exists():
            rep.warn(f"[{sid}] video 文件不存在：{s['video']}（换机器后要改路径）")
        # start_s/end_s 必须有：eval_match_annotations.py 会直接拿它们去切片段（缺了会 KeyError）
        if not (_is_num(s.get("start_s")) and _is_num(s.get("end_s"))):
            rep.err(f"[{sid}] 缺少 start_s/end_s（评测要按它们切片段，缺了跑不起来）")
        elif not float(s["start_s"]) < float(s["end_s"]):
            rep.err(f"[{sid}] start_s({s['start_s']}) 必须小于 end_s({s['end_s']})")
        if not s.get("source_sha256"):
            rep.warn(f"[{sid}] 没写 source_sha256 —— 事后无法确认标的是不是同一份素材")
        times = []
        for i, sh in enumerate(shots):
            if not isinstance(sh, dict):
                rep.err(f"[{sid}] shots[{i}] 不是对象")
                continue
            total += 1
            t = sh.get("release_s")
            if not _is_num(t):
                rep.err(f"[{sid}] shots[{i}] 缺 release_s（出手那一瞬的原片秒）")
            else:
                times.append(float(t))
                _check_sample_span(rep, sid, base, float(t), f"shots[{i}] release_s")
            if sh.get("result") not in ("made", "missed"):
                rep.err(f"[{sid}] shots[{i}] result 只能是 made/missed"
                        f"（现在 {sh.get('result')!r}；看不清就整条别写，不要猜）")
            if sh.get("value") not in (1, 2, 3):
                rep.err(f"[{sid}] shots[{i}] value 只能是 1/2/3（现在 {sh.get('value')!r}）")
            if "is_replay" in sh and not isinstance(sh.get("is_replay"), bool):
                rep.err(f"[{sid}] shots[{i}] is_replay 必须是 true/false")
            elif "is_replay" not in sh:
                rep.warn(f"[{sid}] shots[{i}] 没写 is_replay（转播片里的回放会算成多报）")
        for a, b in zip(sorted(times), sorted(times)[1:]):
            if b - a < 1.5:
                rep.warn(f"[{sid}] 两次出手相隔 {b - a:.2f} s（小于匹配容差 1.5 s）—— "
                         "确认不是同一次出手记了两遍")
    name, target = TARGETS["shots"]
    rep.note(f"出手真值：{total} 次{name}（{incomplete} 段未标完）；建议 ≥{target} 次 —— "
             + ("够了" if total >= target else f"还差 {target - total} 次"))


def check_file(path: Path, base: dict) -> Report:
    rep = Report(Path(path))
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:                                     # noqa: BLE001
        rep.err(f"不是合法 JSON：{type(e).__name__}: {e}")
        return rep
    kind = detect_kind(data)
    if kind == "unknown":
        rep.err("认不出这是哪一类真值（顶层要有 samples，且每个 sample 带 "
                "tracks / possessions / readings / shots 之一）")
        return rep
    rep.note(f"类型判定：{kind}")
    # 时间段以**本文件自己写的 start_s/end_s 为准**，测试集只用来补/交叉核对。
    # 为什么：新的真值文件是另一批素材（id 与老测试集不同），拿老测试集当唯一依据
    # 会把正确的标注全报成「不在测试集里」—— 那是假错误（实测踩到）。
    merged = dict(base)
    for s in data.get("samples") or []:
        if isinstance(s, dict) and s.get("id") is not None:
            sid = str(s["id"])
            if _is_num(s.get("start_s")) and _is_num(s.get("end_s")):
                merged[sid] = {"id": sid, "start_s": s["start_s"], "end_s": s["end_s"]}
            elif sid not in merged:
                merged[sid] = {"id": sid}
    if kind == "jersey":
        check_jersey(rep, data, merged)
    elif kind == "tactics":
        check_tactics(rep, data, merged)
    elif kind == "scoreboard":
        check_scoreboard(rep, data, merged)
    elif kind == "shots":
        check_shots(rep, data, merged)
    if not data.get("annotator"):
        rep.warn("文件头没写 annotator（谁标的）—— 追溯时用得上")
    if not data.get("time_basis"):
        rep.warn("文件头没写 time_basis（时间基准，例如 original_video_seconds）")
    return rep


def default_files(d: Path) -> list:
    """默认检查哪些：`*_split*.json` + `jersey*/tactics*/scoreboard*.json`；
    模板（`*.template.json`）与测试集本身跳过。"""
    out = []
    for p in sorted(Path(d).glob("*.json")):
        n = p.name
        if n.endswith(".template.json") or n.startswith("match_testset"):
            continue
        if ("split" in n) or n.startswith(("jersey", "tactics", "scoreboard")):
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="校验人工真值文件的格式与范围（只读）")
    ap.add_argument("files", nargs="*", type=Path, help="要检查的真值文件（默认扫 eval/ground_truth/）")
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--base", type=Path, default=DEFAULT_BASE, help="测试集（用于核对 sample id 与时间段）")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    base = base_index(args.base)
    files = [Path(f) for f in args.files] or default_files(args.dir)
    if not files:
        print(f"没找到要检查的真值文件（看 {args.dir}）；模板在 {args.dir / 'templates'}")
        return 0
    print(f"测试集索引：{len(base)} 段（{args.base.name}）")
    bad = 0
    for f in files:
        rep = check_file(f, base)
        head = "✅" if rep.ok else "❌"
        print(f"\n{head} {f}")
        for w in rep.warns:
            print(f"   警告：{w}")
        for e in rep.errors:
            print(f"   错误：{e}")
        if not args.quiet:
            for n in rep.notes:
                print(f"   {n}")
        bad += 0 if rep.ok else 1
    print(f"\n合计：{len(files)} 个文件，{len(files) - bad} 个通过，{bad} 个有硬错误")
    if bad:
        print("有硬错误的文件**不要**直接拿来算指标 —— 先按上面的行号改掉。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())

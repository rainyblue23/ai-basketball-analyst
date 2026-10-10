# -*- coding: utf-8 -*-
"""分时段标定：**时间归属**与"按时刻取标定"。

为什么单独一个模块（用户 2026-10-05 的字段表）：多帧解算得到的矩阵属于**哪一个参考帧**、
**哪一段时间**能用，必须显式记下来 —— 否则"摇镜前后各一份标定"根本无从判定，
而"默认整段有效"会把错位的坐标喂给热区与战术图。

字段（照用户的表）：
  capture_time_s   这份标定实际对应的参考帧时刻
  source_frames    参与解算的原始帧及各自点位 [{t, n, landmarks}]
  valid_from_s/to  明确适用时段，**左闭右开** [from, to)
  reference_frame  跨帧补偿最终映射到哪一帧（没有可信补偿时 = capture_time_s）
  verification     独立校验状态、依据与误差 {position_unverified, hoop_checked, ...}

纪律：
  * **不把两幅画面的时间取平均当锚帧**；矩阵属于哪一帧就记哪一帧；
  * **不默认整段有效**：没写 valid_from/to 的标定视为"未指定时段"，按时刻取时直接不可用；
  * 无覆盖 / 时段重叠冲突 / 时段内跨切镜 → 明确返回不可用（附原因），不猜。
"""
from __future__ import annotations

import json
import time as _time
from pathlib import Path
from typing import Any, Optional

DATA = Path(__file__).resolve().parents[2] / "data"

SEG_KEYS = ("capture_time_s", "reference_frame", "valid_from_s", "valid_to_s",
            "source_frames", "verification", "court_model", "point_names", "H")


def calibration_path(video: str | Path) -> Path:
    """这段视频的标定文件路径（**测试可以整体重定向**，见 `set_path_override`）。"""
    if _PATH_OVERRIDE is not None:
        return Path(_PATH_OVERRIDE(str(video)))
    stem = Path(str(video)).stem[:40]
    return DATA / f"calibration_{stem}.json"


# ---------------------------------------------------------------- 路径覆盖（测试用）
# 为什么要有这个入口（实测踩到）：`record_segment()` 走的是**本模块的**
# `calibration_path()`，而测试里打的是 `api._calibration_path_for` —— 于是测试
# "以为"自己隔离好了，实际每跑一次都往真实 `data/` 追加一条 segment
# （`data/calibration_tiny.json` 就这么被累积到 59 段、`calibration_tiny2.json` 到
# 9 段；那儿本来是用户手工标定才该占的位置）。给一个显式的覆盖入口，
# 测试设置它之后读写都落在测试目录里，用户目录一条都不写。
_PATH_OVERRIDE = None          # callable(video) -> Path；None = 用默认的 data/ 路径


def set_path_override(fn) -> None:
    """测试用：重定向本模块所有标定文件读写（传 None 恢复默认）。"""
    global _PATH_OVERRIDE
    _PATH_OVERRIDE = fn


def _read_doc(video: str | Path) -> dict:
    p = calibration_path(video)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return {}


def segments_of(video: str | Path) -> list[dict]:
    """这份视频下所有分时段标定（没有 segments 键时返回空 —— 不把整段当有效）。"""
    doc = _read_doc(video)
    segs = doc.get("segments")
    return [s for s in segs if isinstance(s, dict)] if isinstance(segs, list) else []


def make_segment(calib: dict, *, capture_time_s: Optional[float], reference_frame: Optional[float],
                 source_frames: Optional[list], valid_from_s: Optional[float],
                 valid_to_s: Optional[float], verification: Optional[dict],
                 label: str = "") -> dict:
    """把一次解算的结果整理成一条"分时段标定"记录（字段名照用户的表）。"""
    seg = {k: calib.get(k) for k in SEG_KEYS if k in calib}
    seg.update(capture_time_s=(None if capture_time_s is None else float(capture_time_s)),
               reference_frame=(None if reference_frame is None else float(reference_frame)),
               source_frames=list(source_frames or []),
               valid_from_s=(None if valid_from_s is None else float(valid_from_s)),
               valid_to_s=(None if valid_to_s is None else float(valid_to_s)),
               verification=dict(verification or {}),
               label=label, created_at=_time.strftime("%Y-%m-%d %H:%M:%S"))
    return seg


def overlap_of(segs: list[dict], a: float, b: float) -> Optional[dict]:
    """[a,b) 与已有时段是否重叠（左闭右开）。返回第一个冲突记录。"""
    for s in segs:
        f, t = s.get("valid_from_s"), s.get("valid_to_s")
        if f is None or t is None:
            continue
        if a < float(t) and float(f) < b:
            return s
    return None


def validate_segment(segs: list[dict], valid_from_s, valid_to_s) -> None:
    """时段合法性 + 与已有标定是否重叠。**不做任何写盘**，可以放心在写之前调用。

    边界（用户 2026-10-05）：非有限数 / 负数 / 只填一个端点 / to<=from 一律拒；
    超出视频时长**允许保存**（由调用方记录提示），但这里不检查时长。
    """
    import math as _m
    a, b = valid_from_s, valid_to_s
    if (a is None) != (b is None):
        raise ValueError("适用时段要么都填、要么都不填（只填了一个端点）")
    for v, nm in ((a, "valid_from_s"), (b, "valid_to_s")):
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise ValueError("%s 不是数字" % nm)
        if not _m.isfinite(fv) or fv < 0:
            raise ValueError("%s 必须是非负有限数（收到 %r）" % (nm, v))
    if a is not None and b is not None:
        if float(b) <= float(a):
            raise ValueError("适用时间段不合法：结束必须晚于开始（收到 [%s, %s)）" % (a, b))
        hit = overlap_of(segs, float(a), float(b))
        if hit is not None:
            raise ValueError("本段与已有标定重叠：[%s, %s) 与 [%s, %s) —— 同一时刻只能有一份标定"
                             % (a, b, hit.get("valid_from_s"), hit.get("valid_to_s")))


def record_segment(video: str | Path, seg: dict, revision: Optional[int] = None,
                   bump_revision: bool = True) -> dict:
    """把一条分时段标定写进该视频的标定文件（保留 revision 乐观锁）。

    * 时段重叠 → 抛 ValueError（调用方转 409），**不静默覆盖**；
    * 没写 valid_from/to → 允许写，但记为"未指定时段"，取用时一律不可用；
    * `bump_revision=False`：由调用方负责自增 revision（标定端点在写同一个文件时
      已经加过一次；这里再 +1 会让客户端手上的 revision 立刻过期 → 下次保存被 409 挡住）。
    """
    p = calibration_path(video)
    doc = _read_doc(video)
    old_rev = int(doc.get("revision") or 0)
    if revision is not None and int(revision) != old_rev:
        raise ValueError("revision 冲突：当前 %d，请求 %s" % (old_rev, revision))
    segs = [s for s in (doc.get("segments") or []) if isinstance(s, dict)]
    validate_segment(segs, seg.get("valid_from_s"), seg.get("valid_to_s"))
    segs.append(seg)
    segs.sort(key=lambda s: (s.get("valid_from_s") if s.get("valid_from_s") is not None else 1e9))
    doc["segments"] = segs
    doc["for_video"] = doc.get("for_video") or str(video)
    if bump_revision:
        doc["revision"] = old_rev + 1
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)
    return {"saved": True, "revision": doc["revision"], "segments": len(segs)}


def probe_cuts(video: str | Path, t0: float, t1: float, probes: int = 6) -> dict:
    """在 [t0,t1] 里探一下镜头分段：`{"ok", "parts", "note"}`。

    ⚠️ 关键区分（实测踩到）：**探测失败 ≠ 探到切镜**。
    视频读不出来时 `build_segments` 会把每个探点各算一段（保守拆分），
    若直接当"跨切镜"，会把一份好标定冤枉掉。所以这里必须把两种情形分开：
      * ok=True  → parts 是真实的分段；len(parts) > 1 才算跨切镜；
      * ok=False → 探测失败（视频不可读/依赖缺失），调用方按"证据不足"处理，不猜。
    """
    if t1 <= t0:
        return {"ok": True, "parts": [[t0, t1]], "note": "时段为空"}
    try:
        from .frame_motion import build_segments
        ts = [t0 + (t1 - t0) * (i + 0.5) / probes for i in range(probes)]
        out = build_segments(str(video), ts)
        segs = out.get("segments") or []
        if not segs:
            return {"ok": False, "parts": [[t0, t1]], "note": "分段结果为空"}
        parts = [[float(x) for x in seg.get("times", [])] for seg in segs]
        return {"ok": True, "parts": parts,
                "note": "探到 %d 段（同一镜头内的帧才能共用一份标定）" % len(parts)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "parts": [[t0, t1]], "note": "探测失败：%s" % str(e)[:80]}


def calibration_for_time(video: str | Path, t: float, *, check_cut: bool = False) -> dict:
    """**按时刻取标定**（第一版统一入口）。返回：

        {ok, H, segment, reason, detail}

    reason 取值：no_calibration / no_coverage / segment_conflict / no_segment_time / cut_in_segment
    只有 ok=True 时才给 H；其余一律不可用（调用方**不许**退回"用最近的一份"）。
    """
    segs = segments_of(video)
    if not segs:
        return {"ok": False, "H": None, "segment": None, "reason": "no_calibration",
                "detail": "这段视频还没有分时段标定"}
    hit = [s for s in segs
           if s.get("valid_from_s") is not None and s.get("valid_to_s") is not None
           and float(s["valid_from_s"]) <= t < float(s["valid_to_s"])]   # 左闭右开
    if not hit:
        has_time = any(s.get("valid_from_s") is not None for s in segs)
        return {"ok": False, "H": None, "segment": None,
                "reason": ("no_coverage" if has_time else "no_segment_time"),
                "detail": ("t=%.2fs 不在任何标定的适用时段内" % t) if has_time
                          else "已有标定没有写适用时段（valid_from_s/valid_to_s）—— 不默认整段有效"}
    if len(hit) > 1:
        return {"ok": False, "H": None, "segment": None, "reason": "segment_conflict",
                "detail": "t=%.2fs 落在 %d 份标定的时段里（时段必须互不重叠）" % (t, len(hit))}
    seg = hit[0]
    if check_cut:
        info = probe_cuts(video, float(seg["valid_from_s"]), float(seg["valid_to_s"]))
        if not info.get("ok"):
            # 证据不足 → 暂停（不猜"没切镜"，也不冤枉成"跨了切镜"）
            return {"ok": False, "H": None, "segment": seg, "reason": "cut_unknown",
                    "detail": "无法确认这段里有没有切镜（%s）—— 按证据不足处理，先不产出坐标"
                              % info.get("note")}
        if len(info.get("parts") or []) > 1:
            return {"ok": False, "H": None, "segment": seg, "reason": "cut_in_segment",
                    "detail": "这份标定的适用时段里跨了切镜（%s）—— 切镜后不沿用旧标定"
                              % info.get("note")}
    return {"ok": True, "H": seg.get("H"), "segment": seg, "reason": "ok",
            "detail": "适用时段 [%s, %s)，参考帧 %s"
                      % (seg.get("valid_from_s"), seg.get("valid_to_s"),
                         seg.get("reference_frame"))}


def all_segments_summary(video: str | Path) -> dict:
    segs = segments_of(video)
    return {"revision": int(_read_doc(video).get("revision") or 0), "count": len(segs),
            "segments": [{k: s.get(k) for k in
                          ("label", "capture_time_s", "reference_frame", "valid_from_s",
                           "valid_to_s", "created_at")} for s in segs]}

"""分析管线 —— 把 RawTrack 变成前端/报告需要的所有产物。

  raw_track.json  ──►  pipeline.run()
                         ├── game.json        总览：比分、分节、时间轴、走势
                         ├── players.json     球员统计
                         ├── shotchart.json   热区（点/分区/网格）
                         ├── events.jsonl     完整事件流
                         ├── report.md        文字战报
                         ├── report.json      结构化战报
                         ├── stats.csv        Excel 可打开的统计表
                         ├── highlights/*.mp4 高光片段
                         └── [套餐 B] tactics.json / tactics_frames.jsonl
                             / passes.csv / spacing.csv   战术层产物
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .model import Event, EventType, Player, Shot, write_jsonl
from .rules import (
    RulesConfig, build_shots, compute_player_stats, compute_team_stats,
    quarter_scores, score_progression, shot_chart, possessions, zone_of,
)
from .sources import RawTrack
from .tactics import (
    TacticsConfig, build_tactics, build_tactics_frames, write_tactics_frames,
)
from .report import build_report_md, build_report_json
from .export import write_stats_csv, write_shots_csv, \
    write_passes_csv, write_spacing_csv
from .highlight import make_highlights


@dataclass
class PipelineConfig:
    out_dir: str = "out"
    rules: RulesConfig = field(default_factory=RulesConfig)
    make_highlights: bool = True
    highlight_limit: int = 15
    video_path: Optional[str] = None
    # 人工复核改判：{出手序号: {"made": bool, "value": 1|2|3}}
    # 出手序号 = 按时间排序后的下标，与 game["timeline"] 的下标一致。
    # 有改判时该次出手直接采信人工结论（confidence=1.0，source=manual）。
    overrides: dict = field(default_factory=dict)
    # 人工补录的进球/出手（自动检测漏掉时使用）
    extra_attempts: list = field(default_factory=list)
    # 套餐 B：战术层（控球/传球网络/阵型/空间/俯视战术图）。
    # 关掉它 = 退化成套餐 A 的产物集合，方便对比答辩。
    make_tactics: bool = True
    tactics: Optional[TacticsConfig] = None


@dataclass
class PipelineResult:
    out_dir: str
    game: dict
    players: list[dict]
    shotchart: dict
    shots: list[Shot]
    events: list[Event]
    report_md: str
    files: dict = field(default_factory=dict)
    tactics: Optional[dict] = None

    def summary(self) -> str:
        g = self.game
        extra = ""
        carry = g.get("carry_in") or {}
        policy = str(g.get("score_policy", "scoreboard") or "scoreboard").lower()
        if carry.get("home") or carry.get("away"):
            if policy == "scoreboard":
                extra = (f" | 开局带入 {carry.get('home', 0)}:"
                         f"{carry.get('away', 0)}")
            else:
                extra = (f" | 比分牌参考 {carry.get('home', 0)}:"
                         f"{carry.get('away', 0)}（不计入本片段得分）")
        tac = ""
        if isinstance(g.get("tactics"), dict) and g["tactics"].get("available"):
            t = g["tactics"]
            tac = (f" | 回合 {t.get('possessions', 0)} 次 / 传球 "
                   f"{t.get('passes', 0)} 次 / 阵型 {t.get('formation', '-')}")
        return (f"比分 {g['teams']['home']['name']} {g['score']['home']} : "
                f"{g['score']['away']} {g['teams']['away']['name']}{extra} | "
                f"出手 {len(self.shots)} 次 | 事件 {len(self.events)} 条{tac} | "
                f"产物目录 {self.out_dir}")


def run_pipeline(rt: RawTrack, cfg: Optional[PipelineConfig] = None,
                 progress: Optional[Callable[[float, str], None]] = None
                 ) -> PipelineResult:
    cfg = cfg or PipelineConfig()
    out = Path(cfg.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    def step(p: float, msg: str):
        if progress:
            progress(p, msg)

    step(0.05, "载入检测结果")
    # ---- 1) 出手 -> Shot（计分规则引擎 + 事件融合）----
    step(0.20, "计分规则引擎：分值判定 + 命中融合")
    attempts = [a.to_dict() for a in rt.attempts]
    # 人工补录的出手先并入，再走同一套规则引擎/统计/战报。
    for d in (cfg.extra_attempts or []):
        if not d:
            continue
        d = dict(d)
        d.setdefault("made", True)
        d.setdefault("conf", 1.0)
        d.setdefault("source", "manual")
        d.setdefault("location_source", "manual")
        d.setdefault("location_estimated", False)
        d.setdefault("counts_for_score", True)
        d.setdefault("value_source", "manual")
        d.setdefault("manual", True)
        d.setdefault("x", 0.0)
        d.setdefault("y", 0.0)
        attempts.append(d)
    for d in attempts:
        # made=None / conf=None 表示「没有先验证据」，不要污染融合环节
        for k in ("made", "conf"):
            if d.get(k) is None:
                d.pop(k, None)

    # 人工复核的改判：按时间排序后的下标定位，和 timeline 下标一一对应
    if cfg.overrides:
        order = sorted(range(len(attempts)), key=lambda i: attempts[i]["t"])
        for idx, fix in cfg.overrides.items():
            if 0 <= idx < len(order):
                a = attempts[order[idx]]
                if fix.get("made") is not None:
                    a["made"] = bool(fix["made"])
                    a["conf"] = 1.0
                    a["manual"] = True
                if fix.get("value") in (1, 2, 3):
                    a["is_free_throw"] = (fix["value"] == 1)
                    # 非罚球时若人工指定 2/3 分，用坐标无法表达，这里记录强制分值
                    if fix["value"] in (2, 3):
                        a["forced_value"] = fix["value"]
                    a["manual"] = True

    shots = build_shots(attempts, ball_track=rt.ball_track,
                        scoreboard_events=rt.scoreboard_events, cfg=cfg.rules)
    step(0.45, f"生成 {len(shots)} 次出手记录")

    # ---- 2) 事件流 ----
    events: list[Event] = []
    for e in rt.detections_meta.get("events", []):
        events.append(Event(t=float(e["t"]), type=e["type"],
                            team=e.get("team", ""),
                            player_id=e.get("player_id", ""),
                            period=int(e.get("period", 1))))
    events.sort(key=lambda e: e.t)

    # ---- 3) 统计 ----
    step(0.60, "计算球队/球员统计、热区")
    home = compute_team_stats(shots, "home")
    away = compute_team_stats(shots, "away")
    player_rows = compute_player_stats(shots, rt.players, events)

    # ---- 4) 比分/走势 ----
    prog = score_progression(shots)
    qs = quarter_scores(shots)
    # 开局带入比分（视频从半场中间开始录时比分牌上已有的分）计入总分，
    # 但**不伪造出手**：出手统计仍然只统计本片段里真实发生的那些。
    # 计分口径：court/visual 默认按场上检测到的进球计分，比分牌只作参考；
    # scoreboard 才把比分牌带入分计入总分。
    policy = str(rt.detections_meta.get("score_policy", "scoreboard")
                 or "scoreboard").lower()
    use_carry_for_score = policy == "scoreboard"
    carry = {"home": int((rt.base_score or {}).get("home", 0) or 0),
             "away": int((rt.base_score or {}).get("away", 0) or 0)}
    # 本片段真正打进的分数
    clip_score = {"home": home.points, "away": away.points}
    if use_carry_for_score and (carry["home"] or carry["away"]):
        if qs:
            bp = int(getattr(rt, "base_period", 1) or 1)
            if not (1 <= bp <= len(qs)):
                bp = 1
            qs[bp - 1]["home"] += carry["home"]
            qs[bp - 1]["away"] += carry["away"]
    if use_carry_for_score:
        score = {"home": clip_score["home"] + carry["home"],
                 "away": clip_score["away"] + carry["away"]}
    else:
        score = dict(clip_score)
    meta = _evidence_meta(rt)
    meta["score_policy"] = policy

    # 每节比分要与总分一致 —— 这里做个自检，答辩时能讲「数据一致性校验」
    assert sum(q["home"] for q in qs) == score["home"], "分节比分与总分不一致(home)"
    assert sum(q["away"] for q in qs) == score["away"], "分节比分与总分不一致(away)"

    # ---- 标定是否适用于这段视频 ----
    # 不适用时**不再产出**热区/战术：球场坐标整片错位，画出来像真的但全是垃圾，
    # 比"没有热区"更糟（用户实测反馈：战术图和热点完全不对）。
    _cal = meta.get("calibration_for_value") or {}
    cal_usable = bool(meta.get("calibration_valid", True)) and \
        bool(_cal.get("ok", True))
    cal_reason = ""
    if not cal_usable:
        cal_reason = (_cal.get("reason") or meta.get("calibration_rejected")
                      or "这份球场标定不适用于这段视频（机位/分辨率不匹配）")

    if cal_usable:
        sc = shot_chart(shots)
        zones_by_team = {t: shot_chart(shots, team=t)["zones"]
                         for t in ("home", "away")}
    else:
        sc = {"points": [], "zones": {}, "bin_size": 0.0,
              "unavailable": True, "reason": cal_reason}
        zones_by_team = {t: {} for t in ("home", "away")}
    meta["court_outputs_available"] = cal_usable
    if not cal_usable:
        meta["court_outputs_reason"] = cal_reason

    game = {
        "score": score,
        "clip_score": clip_score,
        "score_policy": policy,
        "scoreboard_reference": carry,
        "teams": {
            "home": {"name": _team_name(rt, "home") or "主队",
                     "stats": home.to_dict()},
            "away": {"name": _team_name(rt, "away") or "客队",
                     "stats": away.to_dict()},
        },
        "quarter_scores": qs,
        "progression": prog,
        "timeline": [_shot_event(s, rt) for s in sorted(shots, key=lambda x: x.t)],
        "periods": 4,
        "duration": rt.duration,
        "fps": rt.fps,
        "needs_review": [s.to_dict() for s in shots if "needs_review" in s.tags],
        "possessions": len(possessions(shots)),
        "carry_in": carry,
        "base_period": int(getattr(rt, "base_period", 1) or 1),
        "judgement": _judgement(meta, shots),
        "unmatched_goals": [s.to_dict() for s in shots
                            if s.made and not s.counts_for_score],
        "meta": meta,    }

    # ---- 4.5) 套餐 B：战术层 ----
    # 放在统计之后、战报之前：战报要引用战术结论（阵型占比 / 传球网络摘要）。
    tactics_data: Optional[dict] = None
    tactics_frames: list[dict] = []
    if cfg.make_tactics and not cal_usable:
        # 战术层整层都建立在球场坐标上 —— 标定错，它就整层错。
        # 这里明确标成"不适用"，而不是给一张错的俯视图。
        step(0.68, "战术层：跳过（球场标定不适用于这段视频）")
        game["tactics"] = {"available": False, "reason": cal_reason,
                           "note": "球场标定不适用，战术分析（控球/传球网络/阵型/"
                                   "空间/俯视图）无法计算"}
    elif cfg.make_tactics:
        step(0.68, "战术层：控球归属 / 传球网络 / 阵型 / 空间")
        tcfg = cfg.tactics or TacticsConfig()
        # 注意这里传的是**已定稿的 shots**（含人工复核改判），
        # 这样"这次回合拿了多少分"跟记分牌、战报永远是同一口径。
        tactics_data = build_tactics(
            rt.player_track, rt.ball_track, rt.players, shots,
            duration=rt.duration, cfg=tcfg)
        if tactics_data.get("available"):
            tactics_frames = build_tactics_frames(
                rt.player_track, rt.ball_track, duration=rt.duration, cfg=tcfg)
        game["tactics"] = _tactics_summary(tactics_data)

    # ---- 5) 战报 ----
    step(0.72, "生成战报")
    report_json = build_report_json(game, player_rows, shots, tactics_data)
    report_md = build_report_md(game, player_rows, shots, zones_by_team,
                                tactics_data)

    # ---- 6) 导出 ----
    step(0.82, "导出 CSV / JSON")
    Path(out, "game.json").write_text(
        json.dumps(game, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(out, "players.json").write_text(
        json.dumps(player_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(out, "shotchart.json").write_text(
        json.dumps({"all": sc, "by_team": zones_by_team},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    Path(out, "report.json").write_text(
        json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    Path(out, "report.md").write_text(report_md, encoding="utf-8")
    write_jsonl(str(Path(out, "events.jsonl")),
                [s.to_dict() for s in shots] +
                [e.to_dict() for e in events])
    write_stats_csv(str(Path(out, "stats.csv")), player_rows, home, away)
    write_shots_csv(str(Path(out, "shots.csv")), shots)

    if tactics_data is not None:
        Path(out, "tactics.json").write_text(
            json.dumps(tactics_data, ensure_ascii=False, indent=2),
            encoding="utf-8")
        write_tactics_frames(str(Path(out, "tactics_frames.jsonl")),
                             tactics_frames)
        write_passes_csv(str(Path(out, "passes.csv")), tactics_data)
        write_spacing_csv(str(Path(out, "spacing.csv")), tactics_data)

    files = {
        "game": "game.json", "players": "players.json",
        "shotchart": "shotchart.json", "events": "events.jsonl",
        "report_md": "report.md", "report_json": "report.json",
        "stats_csv": "stats.csv", "shots_csv": "shots.csv",
    }
    if tactics_data is not None:
        files["tactics"] = "tactics.json"
        files["tactics_frames"] = "tactics_frames.jsonl"
        files["passes_csv"] = "passes.csv"
        files["spacing_csv"] = "spacing.csv"

    # ---- 7) 高光 ----
    clips: list[dict] = []
    if cfg.make_highlights:
        step(0.88, "生成高光片段")
        video = cfg.video_path or rt.video_path
        clips = make_highlights(shots, video, str(out / "highlights"),
                                limit=cfg.highlight_limit, cfg=cfg.rules,
                                duration=rt.duration)
        files["clips"] = "highlights/index.json"
    game["highlights"] = clips
    Path(out, "game.json").write_text(
        json.dumps(game, ensure_ascii=False, indent=2), encoding="utf-8")

    step(1.0, "完成")
    return PipelineResult(out_dir=str(out), game=game, players=player_rows,
                          shotchart=sc, shots=shots, events=events,
                          report_md=report_md, files=files,
                          tactics=tactics_data)


def _tactics_summary(t: Optional[dict]) -> dict:
    """把战术结论压成一个小摘要塞进 game.json。

    完整数据在 tactics.json（几百 KB），而 game.json 是每个页面都会拉的，
    所以这里只放"总览页/侧边栏一眼能看完"的几个数，再加上一个 available 标记 ——
    战术页据此决定是去拉 tactics.json 还是直接提示"本场没有球员轨迹"。
    """
    if not t:
        return {"available": False, "reason": "战术层未启用"}
    if not t.get("available"):
        return {"available": False, "reason": t.get("reason", "")}
    poss = t.get("possession") or {}
    passes = t.get("passes") or {}
    form = t.get("formation") or {}
    summary = {}
    for team, d in (form.get("summary") or {}).items():
        off = (d.get("offense") or [{}])[0].get("label", "-")
        deff = (d.get("defense") or [{}])[0].get("label", "-")
        summary[team] = {"offense": off, "defense": deff}
    return {
        "available": True,
        "possessions": poss.get("total", 0),
        "avg_passes": poss.get("avg_passes", 0),
        "passes": passes.get("total", 0),
        "turnovers": passes.get("turnovers", 0),
        "attack_side": t.get("attack_side", ""),
        "formation": summary,
        "spacing": (t.get("spacing") or {}).get("teams", {}),
        "coverage": t.get("coverage", {}),
    }


def _evidence_meta(rt: RawTrack) -> dict:
    """把「这次判定用了哪几路证据、各自的质量如何」写进 game.json。

    答辩时最有用的信息：比分是哪来的、球追到了多少、分队是怎么分的。
    这里只保留摘要，完整读数在 raw_track.json 里。
    """
    d = rt.detections_meta or {}
    meta = {"source": d.get("source", "unknown"),
            "fps": rt.fps, "duration": rt.duration}
    sb = d.get("scoreboard")
    if sb:
        meta["scoreboard"] = {
            "frames_hit": sb.get("frames_hit"), "frames_read": sb.get("frames_read"),
            "bug": sb.get("bug"),
            "events": [e for e in sb.get("events", []) if e.get("kind") == "score"],
        }
    if d.get("visual"):
        meta["visual"] = d["visual"]
    if d.get("hoop"):
        meta["hoop"] = {k: v for k, v in d["hoop"].items() if k != "samples"}
    if "calibration_valid" in d:
        meta["calibration_valid"] = d["calibration_valid"]
    if d.get("visual_error"):
        meta["visual_error"] = d["visual_error"]
    if d.get("final_score"):
        meta["scoreboard_final"] = d["final_score"]
    if d.get("ball"):
        meta["ball"] = d["ball"]
    if d.get("attempts"):
        meta["attempts"] = d["attempts"]
    if d.get("teams"):
        meta["teams"] = d["teams"]
    if d.get("scoreboard_error"):
        meta["scoreboard_error"] = d["scoreboard_error"]
    return meta


def _judgement(meta: dict, shots: list) -> dict:
    """这次到底「判出来了」还是「判不了」，以及为什么。

    存在的意义：以前判不出来的时候，产物里就是一个 0 : 0，界面上写着「平局」。
    那是在误导人 —— **0:0 表示"没检测到得分"，不等于"双方都没得分"**。
    这里把状态和原因显式记下来，战报和界面就能说人话。
    """
    sb = meta.get("scoreboard") or {}
    vis = meta.get("visual") or {}
    if meta.get("source") == "synthetic":
        return {"state": "synthetic", "note": "合成数据（demo），比分是构造出来的"}
    policy = str(meta.get("score_policy", "scoreboard") or "scoreboard").lower()
    if policy in ("court", "visual", "auto"):
        made = [s for s in shots if s.made]
        note = (f"按场上检测到的进球计分：本片段 {len(made)} 次命中，"
                f"合计 {sum(s.points for s in made)} 分。") if made else \
               "本片段未检测到进球。"
        fin = meta.get("scoreboard_final") or {}
        if fin:
            note += (f" 比分牌读数 {fin.get('home', 0)} : {fin.get('away', 0)}"
                     " 仅作参考，不计入本片段得分。")
        return {"state": "court", "note": note}
    if sb.get("frames_hit"):
        unmatched = [s for s in shots if s.made and not s.counts_for_score]
        counted = [s for s in shots if s.made and s.counts_for_score]
        note = f"比分由广播比分牌给出（读到 {sb.get('frames_hit')} 帧）"
        if unmatched:
            note += (f"；视觉路径另有 {len(unmatched)} 次命中未被比分牌确认，"
                     "未计入总分")
        elif counted:
            note += f"；另有 {len(counted)} 次视觉命中已计入总分"
        return {"state": "scoreboard", "note": note}
    if shots:
        return {"state": "visual",
                "note": f"由「球 + 篮筐」路径判出 {len(shots)} 次出手"}
    reasons = []
    if meta.get("scoreboard_error"):
        reasons.append("比分牌：" + str(meta["scoreboard_error"]).split("\n")[0][:90])
    elif sb.get("frames_read"):
        reasons.append(f"比分牌：一帧都没读出来（0/{sb['frames_read']}）——"
                       "这段视频的台标和已标定的模板不匹配")
    else:
        reasons.append("比分牌：未启用")
    if meta.get("visual_error"):
        reasons.append("视觉路径：" + str(meta["visual_error"]).split("。")[0][:90])
    unmatched = [s for s in shots if s.made and not s.counts_for_score]
    if unmatched:
        return {"state": "visual_unconfirmed",
                "note": (f"视觉路径检测到 {len(unmatched)} 次命中，但比分牌在本片段"
                         "没有对应得分事件（可能是回放/误检），因此没有计入总分；"
                         "命中已保留在高光和报告里，可在复核页确认。"),
                "reasons": reasons}
    return {"state": "cannot_judge",
            "note": "本片段没有识别到任何得分事件",
            "reasons": reasons}


def _team_name(rt: RawTrack, team: str) -> str:
    """给球队取个能看的名字。

    优先级：
      1. 数据源直接给的名字（野球场/1v1 场景下会用「球员1/球员2」）
      2. 球员名字（合成数据是「主队1号」这种）
    真视频链路里球员名字默认就是跟踪 ID（T143），直接用会得到两队都叫「T」，
    所以要把它识别出来并退回「主队/客队」。
    """
    named = (rt.detections_meta.get("team_names") or {}).get(team)
    if named:
        return named
    for p in rt.players.values():
        if p.team != team:
            continue
        n = p.name.replace("号", "")
        if re.fullmatch(r"[Tt]\d+", n):        # 纯跟踪 ID，不是真名字
            continue
        n = n.rstrip("0123456789")
        if n:
            return n
    return "主队" if team == "home" else "客队"


def _shot_event(s: Shot, rt: RawTrack) -> dict:
    name = rt.players[s.player_id].name if s.player_id in rt.players else s.player_id
    return {"t": round(s.t, 2), "team": s.team, "player_id": s.player_id,
            "player": name, "value": s.value, "made": s.made,
            "points": s.score_points, "counts_for_score": s.counts_for_score,
            "value_estimated": "value_estimated" in s.tags,
            "x": round(s.x, 2), "y": round(s.y, 2),
            "zone": zone_of(s.x, s.y), "confidence": s.confidence,
            "source": s.outcome_source, "period": s.period}

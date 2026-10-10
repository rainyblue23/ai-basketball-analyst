# -*- coding: utf-8 -*-
"""回归测试：`_judgement` 的那句话不能和比分对不上。

背景（实测踩到，2026-10-05）：4 分钟真视频任务 6038f6b8326a 的产物里，
`game.json.judgement.note` 写的是「本片段 **4 次命中，合计 8 分**」，
而 `game.score` 是 **2:4（6 分）**，`meta.visual.made` 是 4。
差的正是那次 `counts_for_score=False` 的命中。

根因：note 用 `sum(s.points)` 求和，而 `Shot.points` 的定义是
「这次出手本身的得分（不管是否计入总分）」（`model.py:128`），
计分口径用的是 `Shot.score_points`（`model.py:133`，未计入总分时为 0）。

跑法：python tests/test_judgement_note.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aihoop.model import Shot                      # noqa: E402
from aihoop.pipeline import _judgement             # noqa: E402

META = {"score_policy": "court", "source": "video"}


def shots_of_6038f6b8326a() -> list:
    """按 job 6038f6b8326a 的真实产物复刻 5 条出手（3 计入 + 1 不计入 + 1 未知）。"""
    return [
        Shot(t=26.99, team="away", player_id="A", made=True, counts_for_score=True, value=2, result="made"),
        Shot(t=47.71, team="home", player_id="B", made=True, counts_for_score=True, value=2, result="made"),
        Shot(t=117.12, team="away", player_id="A", made=True, counts_for_score=True, value=2, result="made"),
        Shot(t=161.36, team="home", player_id="C", made=True, counts_for_score=False, value=2, result="made"),
        Shot(t=54.19, team="home", player_id="B", made=True, counts_for_score=False, value=3, result="unknown"),
    ]


def main() -> int:
    shots = shots_of_6038f6b8326a()
    note = _judgement(META, shots)["note"]

    # 1) 「合计 N 分」必须等于真正计入比分的总分（这里 3×2 = 6）
    counted = [s for s in shots if s.made and s.counts_for_score]
    expect_pts = sum(s.score_points for s in counted)
    assert expect_pts == 6, f"构造数据本身有问题：expect_pts={expect_pts}"
    assert "合计 6 分" in note, f"合计分与比分不一致：{note}"
    assert "合计 8 分" not in note, f"又把不计分的命中算进去了：{note}"

    # 2) 命中次数也只数计入得分的那几次
    assert "3 次命中" in note, f"命中次数不对：{note}"

    # 3) 判为命中但未计分的那几次，必须单独说清楚（不能悄悄吞掉）
    assert "未计入得分" in note, f"没有说明未计分的命中：{note}"

    # 4) 全部命中都不计分时，不能写成"0 次命中，合计 0 分"
    odds = [s for s in shots if not s.counts_for_score]
    note2 = _judgement(META, odds)["note"]
    assert "0 次命中" not in note2, f"零计入时的话术会误导：{note2}"
    assert "都没有计入得分" in note2, f"零计入时没说清：{note2}"

    # 5) 一次都没命中时，保持原来那句话（别被这次改动带坏）
    note3 = _judgement(META, [s for s in shots if not s.made])["note"]
    assert note3 == "本片段未检测到进球。", f"没进球时的话术变了：{note3}"

    print("OK：")
    print("  ", note)
    print("  ", note2)
    print("  ", note3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

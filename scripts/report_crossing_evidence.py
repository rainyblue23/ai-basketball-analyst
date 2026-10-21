"""Reports and clickable error index from audit artifacts; never edits truth."""
import csv
import html
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crossing_evidence_audit import ROOT, OUT, read, write


def main():
    metrics = read(OUT/"baseline_metrics.json")
    rows = read(OUT/"event_errors.json")
    imported = read(OUT/"annotation_audit.json")
    tasks = read(OUT/"review/tasks.json")
    runtime = read(OUT/"runtime.json")
    resources = read(OUT/"resources.json")["samples"]
    evidence = []
    for task in tasks:
        frames = read(OUT/"review"/task["trace"])
        crossings = []
        for f in frames:
            for arm in ("A", "B"):
                s = f["states"][arm]
                if s["crossing_t"] is None or abs(s["crossing_t"]-f["t"]) > 1e-7:
                    continue
                prev, cur, rim = s["previous_real_xy"], s["smoothed_xy"], f["tracked_rim"]
                if not (prev and cur and rim) or cur[1] == prev[1]:
                    continue
                x = prev[0]+(rim["cy"]-prev[1])/(cur[1]-prev[1])*(cur[0]-prev[0])
                crossings.append(dict(arm=arm, t=f["t"], frame=f["frame"],
                    entered_t=s["entered_t"], entry_expired=s["entry_expired"],
                    real_gap_s=f["t"]-s["previous_real_t"] if s["previous_real_t"] is not None else None,
                    normalized_center_offset_halfwidth=(x-rim["cx"])/(rim["w"]/2),
                    selected_ball_predicted=(f["ball"] or {}).get("predicted"),
                    ball_width_to_rim_width=(f["ball"]["xyxy"][2]-f["ball"]["xyxy"][0])/rim["w"] if f["ball"] else None,
                    tracked_rim_fresh=rim["fresh"], rebound_state=s["rebound"],
                    true_ball_identity="PENDING_VALIDATION", true_aperture="PENDING_VALIDATION",
                    depth_and_occlusion="UNKNOWN", physical_made="not inferred from crossing"))
        evidence.append(dict(task_id=task["id"], crossings=crossings,
            detected_frames=sum(bool(f["ball"]) and not f["ball"].get("predicted") for f in frames),
            predicted_frames=sum(bool(f["ball"]) and f["ball"].get("predicted") for f in frames),
            missing_frames=sum(not f["ball"] for f in frames), total_frames=len(frames),
            physical_failure_module="PENDING_HUMAN_REVIEW"))
    write(OUT/"crossing_evidence_summary.json", evidence)
    with (OUT/"human_review_tasks.csv").open("w", encoding="utf-8-sig", newline="") as file:
        w = csv.writer(file)
        w.writerow(["task_id","source_sha256","review_start_s","review_end_s","purpose","status","human_visual_result","event_identity"])
        for t in tasks:
            w.writerow([t["id"], t["source_sha256"], t["start_s"], t["end_s"], t["purpose"], "pending", "UNKNOWN", "UNKNOWN"])
    # Relative clip links allow a static localhost server rooted at OUT.
    links = []
    for r in rows:
        t = r["truth_t"] if r.get("truth_t") is not None else r["model_t"]
        url = f'baseline/{r["sample"]}/evaluation_segment.mp4#t={max(0,t-3):.3f},{t+5:.3f}'
        links.append("<tr>"+"".join(f"<td>{html.escape(str(r.get(k,'')))}</td>" for k in
            ("sample","truth_id","truth_t","truth_result","model_t","model_result","shot","made"))+
            f'<td><a href="{url}">连续画面 {t:.2f}s</a></td></tr>')
    (OUT/"event_errors.html").write_text("""<!doctype html><meta charset="utf-8">
<title>三段开发视频逐事件对账</title><style>body{font:16px/1.6 system-ui;margin:30px}
td,th{padding:8px;border-bottom:1px solid #ddd}a{color:#164d8e}</style>
<h1>三段开发视频逐事件对账</h1><p>±1.5秒一对一匹配；未匹配FP不等于已确认传球/运球。
人工视频秒数；完整比赛原片偏移UNKNOWN。播放的是本轮实际推理输入，无人工修正。</p>
<table><tr><th>来源</th><th>人工ID</th><th>人工秒</th><th>人工结果</th><th>模型秒</th>
<th>模型结果</th><th>出手</th><th>命中</th><th>回看</th></tr>"""+"\n".join(links)+"</table>", encoding="utf-8")
    gpu = [r["gpu_device_sample"].split(", ") for r in resources if "gpu_device_sample" in r]
    performance = dict(wall_s=runtime["elapsed_s"], samples=len(resources),
        rss_peak_gib=max(r.get("process_tree_rss_bytes",0) for r in resources)/2**30,
        device_gpu_memory_peak_mib=max(float(g[1]) for g in gpu),
        device_gpu_util_average_pct=statistics.mean(float(g[2]) for g in gpu),
        device_gpu_util_peak_pct=max(float(g[2]) for g in gpu),
        device_power_peak_w=max(float(g[3]) for g in gpu),
        limitations="Device-level GPU figures include desktop apps. Sampled every ~5s, peaks between samples unobserved. "
                    "CPU ffmpeg review-clip generation overlapped part of this run; not a clean performance benchmark.")
    write(OUT/"performance_summary.json", performance)
    lines = ["# 穿筐证据审计与三段开发视频回归", "",
        "2026-10-20。本轮不改命中算法。`make_window_from_crossing=false`。不训练、不部署、不修改真值。",
        "", "## 交付入口", "",
        "- [五条穿筐审核任务](review/index.html)：原画与推理输入分开，检测/预测/跟踪框可见，人工球框与篮圈开口框按时间记录；允许UNKNOWN；浏览器草稿与导出文件均不自动导入真值。",
        "- [审核任务清单](human_review_tasks.csv) · [穿越逐帧摘要](crossing_evidence_summary.json)",
        "- [全部逐事件回看](event_errors.html) · [CSV](event_errors.csv) · [完整模型依据](baseline/)",
        "- [独立人工审核模板](review/human_review_template.json)",
        "", "## 原版自动回归（59次画面出现口径）", "",
        "使用与31条基线一致的standard/640/players=false/scoreboard=false/auto_sliding=false/ROI=false。"
        "直接调用VideoSource，不加载curated样例或人工修正。源码/原始标注/模型哈希核对见protected_after.json。",
        "不开球员检测的离手估计可能偏晚；这些数字是这个冻结配置的结果，不代表样例页面人工修正后的表现。",
        "", "|视频|人工出现|引擎事件|出手TP/FP/FN|命中TP/FP/FN|UNKNOWN|", "|---|---:|---:|---|---|---:|"]
    for s in metrics["samples"]:
        a, b = s["shots"], s["made"]
        lines.append(f"|{s['id']}|{s['appearances']}|{s['engine_events']}|{a['TP']}/{a['FP']}/{a['FN']}|{b['TP']}/{b['FP']}/{b['FN']}|{s['UNKNOWN']}|")
    lines += ["", "Precision/Recall/F1均在[结构化指标](baseline_metrics.json)中。没有任何MADE输出的来源，命中Precision是null（无定义），不是100%。"
        "UNKNOWN独立保留。传球/运球/争球误报细分均为pending，不能把未匹配直接命名为其中一种。",
        "", "## 事件类型", "", "|来源|人工类型|条数|出手FN|命中FN|命中FP|", "|---|---|---:|---:|---:|---:|"]
    for s in metrics["samples"]:
        for name, x in s["types"].items():
            lines.append(f"|{s['id']}|{name}|{x['truth']}|{x['shot_FN']}|{x['made_FN']}|{x['made_FP']}|")
    lines += ["", "类型只依据已导入记录的罚球/备注/明确分值。空接、篮下等未归类条目落在other_or_unspecified，不自行补造类型。"
        "无对应真值的额外事件无法分配错误类型。",
        "", "## 人工记录与来源身份", "",
        "yang/lillard/harden全部已导入且本轮重新核验视频SHA一致。不是缺文件；也不是新增加到旧31条中的独立样本。",
        "59次出现按±1.5秒逐次匹配，Lillard的141/159/171秒属于同一个play_id，其中后两次是回放；全体57个play_id。"
        "去回放只另报‘至少一次出现被检出’的描述统计，不冒充独立57次评测，也不在未知回放边界内擅自删除FP。",
        "用户声明三段完整审核，因此可以在对应完整区间计协议FP；整场source_match_id、原片偏移仍pending。"
        "审核区间外不计负例。本轮区间就是各自完整视频，没有扩展。",
        "被盖：Lillard21秒，已记missed并单独分类。Harden约116秒补扣保留独立出手及近似时间提醒；8条分值仍未知，不影响made/missed评估，但不能评价2/3分。",
        "", "## 五个案例：可证明与待确认", "",
        "四条结果案例保留原人工MADE/MISSED；视觉证据新表全部pending。170秒是身份审核任务，171.67秒不能在固定容差外自动关联。",
        "实测框只表示检测器输出，不能证明选对真球。crossing是平滑球心穿过跟踪矩形中心线，不是独立篮圈开口。"
        "当前trace无真实球像素分割、篮圈开口轮廓、遮挡顺序真值，因此不能在本轮把假进归因到前/后掠过或弹框的具体数量。",
        "exit_t没有独立持久化字段，审核页保留null并给原因；另列geometric_exit_sample，"
        "它仅表示实测下方+横向区域成立，不能改名为真实出筐。",
        "15秒的入口过期因果已由上轮固定感知A/B证实；56秒负例则说明仅建立穿越后窗口仍会假进，且已有多帧实测，不能承诺‘再要两帧’就解决。",
        "", "## 本地运行资源", "",
        f"- RTX4060串行三段总耗时：{performance['wall_s']:.2f}秒；包含解码/CRF18重编码/推理/保存/评估。",
        f"- 采样{performance['samples']}次，推理进程树RSS峰值{performance['rss_peak_gib']:.2f}GiB。",
        f"- 整卡显存采样峰值{performance['device_gpu_memory_peak_mib']:.0f}MiB；GPU利用率平均{performance['device_gpu_util_average_pct']:.1f}%、峰值{performance['device_gpu_util_peak_pct']:.0f}%。",
        "- GPU数据包含Codex/QQ等桌面进程，且部分时间同时生成CPU审核片段；不是无竞争的纯推理性能基准。"
        "WDDM每进程显存N/A保留原值，不伪造独占值。详见resources.json、runtime.json、performance_summary.json。",
        "", "## 下一步与是否进入正式跨比赛测试", "",
        "**尚不具备正式独立跨比赛验收条件。** 目前只有开发/已暴露验证来源，旧4段测试仍隔离；"
        "三段Bili本轮已用于诊断，不能再当未见测试。先完成人工穿筐审核与真实比赛身份核对，再招募未训练未调参的新比赛。",
        "需用户补充：五条审核的真球、篮圈开口与遮挡/反弹证据；170秒事件身份；"
        "三段整场比赛日期/对阵或原片链接与剪辑映射（集锦可用分段映射，不能强设单个偏移）；"
        "11条额外事件的传球/运球/争球/真实出手分类。已有视频文件不缺。",
        "", "算法设计与下一轮单因素计划见项目docs/CROSSING_EVIDENCE_DESIGN_20261020.md。"
        "报告中的时间点仅用于审核索引，从未传给推理分支。"]
    (OUT/"REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(OUT/"REPORT.md")


if __name__ == "__main__":
    main()

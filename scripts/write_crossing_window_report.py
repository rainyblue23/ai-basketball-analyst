"""Format measured experiment results; does not rerun or tune inference."""
from pathlib import Path
import json,csv,hashlib

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'out/crossing_window_20261020'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8-sig'))
def save(name,text):(OUT/name).write_text(text,encoding='utf-8')
def triple(d):return '/'.join(str(d[k]) for k in ('TP','FP','FN'))

results=read('results.json');rows=read('per_event_ab.json');imports=read('annotation_import_check.json')
diagram='''sequenceDiagram
    participant O as 真实选球与跟踪筐
    participant A as A 默认入口时钟
    participant B as B 穿越时钟（仅离线）
    O->>A: f456 15.215200 建立 attempt
    O->>B: f456 15.215200 建立 attempt
    O->>A: f464 15.482133 entered=true（宽入口带）
    O->>B: f464 15.482133 entered=true
    Note over A: 截止 16.382133；不会清除 entered
    O->>A: f491 16.383033 首个入口过期帧，无球
    O->>B: f494 16.483133 最近真实球仍高于筐心
    O->>A: f495 16.516500 真实向下 crossing + below出口
    Note over A: crossing 活跃，但入口窗口过期，拒绝 MADE
    O->>B: f495 16.516500 同一输入，crossing=true
    Note over B: 穿越截止 17.416500；回弹=false
    B-->>O: 同帧 MADE（没有额外后验等待）
    O->>A: f501 16.716700 far_below，left_streak=1
    O->>A: f502 16.750067 far_below，left_streak=2
    A-->>O: MISSED（不是 3.5 秒总超时）
'''
save('state_timing.mmd',diagram)
config='''# Offline A/B only. Do not merge this override into product defaults.
# A (production unchanged)
score:
  make_window_from_crossing: false
  make_window_s: 0.9

# B is a separate in-memory copy of the recorded config:
# score.make_window_from_crossing: true
# Every other config value is identical; full configs are in *_config.json.
# Matching tolerance remains 1.5 seconds and is an evaluator parameter.
'''
save('config_difference.yaml',config)

lines=['# 投篮命中窗口过期：单项离线实验','',
'日期：2026-10-20。结论：**拒绝启用；现有正式默认保持不变。** 目标真命中恢复，但新增真实负例 FP，不能满足防假命中条件。', '',
'## 实验范围与可复现性','',
'本轮只运行一个算法对照：已有 `score.make_window_from_crossing: false → true`。复用现有通用算法，没有新增按比赛/时间/标签分支，没有搜索阈值，没有叠加 strict_shot_gate 或遮挡兜底。该开关只在回放 B 的内存配置中开启，产品源码和默认配置未修改。', '',
'运行：在项目根目录设置 PYTHONPATH 为 `src` 与相邻 `aihoop_assets/libs` 后，执行 `python -B scripts/crossing_window_experiment.py`；安全测试为 `python -B tests/test_crossing_window_experiment.py`。', '',
'三段 A 的完整引擎事件均与保存的 GPU 推理事件逐字段相等（exact=True）。A/B 固定球与筐感知输入，只研究状态机因果；不是重新 GPU 推理 B，也不是独立比赛泛化验证。31 条审核基线全部纳入，game03 仍为 Validation_exposed，Independent Test=0。人工标签仅在回放结束后进行一对一评估，未传给 ScoreEngine。匹配调用显式固定 ±1.5 秒。', '',
'[预声明与验收条件](predeclared_plan.json) · [配置差异](config_difference.yaml) · [完整结果](results.json) · [逐事件 CSV](per_event_ab.csv) · [输入摘要](inputs.json) · [保护文件哈希](protected_hashes.json)', '',
'## 当前状态机与窗口语义','',
'实现位置：`src/aihoop/legacy_shots/scorer.py` 的 Attempt、ScoreEngine.update、_advance_without_ball、_advance_without_rim、finalize、_close；默认来自 `legacy_shots/stream.py`。', '',
'1. 真实球、fresh 筐、无待解锁事件且接近篮筐时建立 attempt；无球员绑定的 release_t 是进入接近区域时刻，不是精确人工离手。',
'2. entered 由真实球的三点中位数坐标进入宽入口带置位；entered_t 只记录首次入口，不会随持续接近而刷新。入口横向范围默认 1 倍筐宽，纵向为筐框上下各扩 1 倍筐高，因此可以在上升阶段提前置位。',
'3. 相邻真实观测间隔 0 < dt ≤ 0.5 秒，平滑球心从筐心之上落到之下，插值 crossing_x 落在半筐宽内，才能建立 crossing_t。crossing_t 记录证据建立帧的时间，不是插值求得的精确物理穿越时刻；上升且回到筐心以上会清除 crossing。',
'4. 出口要求 below_rim（超过筐底 + 0.6 倍筐高）、横向不超过当前出口阈值（默认整筐宽）、连续真实观测且继续下落、real_obs≥2、crossing 在 0.9 秒内。预测球不置 entered/crossing，也不确认 MADE。',
'5. A 另外要求 t-entered_t≤0.9 秒。B 把最后一个条件改为 `(开关且未见回弹) OR 入口未过期`，从 crossing_t 起取得独立截止时间。它不是全局回弹否决：入口未过期时 OR 的右支仍可成立；不应将其描述为全场景反弹防护。',
'6. 连续两次真实观测离开接近区或 far_below，或 attempt 超过 3.5 秒后收尾；缺入口/穿越、丢球、筐失效和片尾可成为 UNKNOWN。入口时窗过期只是条件布尔值，不会自动清空状态或立刻发出 MISSED。切镜由回放调用 finalize 后重建引擎，筐 generation 改变也截断证据链。', '',
'## 重点案例：game01 人工约 15 秒 MADE','',
'人工离手约 15 秒；自动事件 release_t=15.22（内部 start_t=15.215200）。', '',
'|帧序号（零基 trace）|时间/秒|状态变化|','|---:|---:|---|',
'|456|15.215200|建立 attempt，entered=false|',
'|464|15.482133|首次 entered=true；球仍高于筐心，处于宽入口带|',
'|—|16.382133|入口截止=15.482133+0.9，端点包含；这是计算时刻，不是解码帧|',
'|491|16.383033|首个入口过期采样；当帧无球；entered 仍为 true|',
'|494|16.483133|真实球观测，平滑 y=226.553，仍在筐心之上|',
'|495|16.516500|平滑 y=282.154；筐心 y=238.700、筐底=252.860；建立 crossing，同时满足出口|',
'|495 B|16.516500|连续间隔约0.033367秒，未见回弹；B 立即 MADE，写出 t=16.52|',
'|501 A|16.716700|far_below 连续计数=1|',
'|502 A|16.750067|far_below 连续计数=2，A MISSED，写出 t=16.75|', '',
'crossing 建立时距首次入口 **1.034367 秒**，已超期 **0.134367 秒**。B 的穿越窗口为 [16.516500,17.416500]，但出口在起点同帧就已满足，没有等待额外穿越后观测。A 的总超时理论截止约18.715200，因此本例并非总 miss_timeout 触发。', '',
'时序中的帧来自保存 trace 的实际 frame 索引；时间来自引擎输入，非人工离手精确帧或整场原片帧号。完整 before/after/close 状态逐帧保存在 `*_A_states.json`、`*_B_states.json`，重点区间另存 `target_A_timeline.json`、`target_B_timeline.json`，包括原始检测球、预测标记、跟踪筐、真实观测计数、回弹、left_streak、窗口期限和事件。', '',
'```mermaid',diagram.rstrip(),'```','',
'## 完整 31 条基线回归','',
'UNKNOWN 是引擎事件的未知结果数量，与出手 TP/FP/FN 和命中 TP/FP/FN 分别统计；不把 UNKNOWN 当 MISSED。表内三元组顺序均为 TP/FP/FN。', '',
'|样本|真值数|A 出手|B 出手|A 命中|B 命中|A UNKNOWN|B UNKNOWN|','|---|---:|---|---|---|---|---:|---:|']
for s in results['samples']:
    a,b=s['A'],s['B'];lines.append(f"|{s['sample']}|{s['truth_count']}|{triple(a['shot'])}|{triple(b['shot'])}|{triple(a['made'])}|{triple(b['made'])}|{a['UNKNOWN']}|{b['UNKNOWN']}|")
a,b=results['A'],results['B'];lines.append(f"|合计|31|{triple(a['shot'])}|{triple(b['shot'])}|{triple(a['made'])}|{triple(b['made'])}|{a['UNKNOWN']}|{b['UNKNOWN']}|")
lines += ['', '出手 P/R/F1 两臂均为 78.79% / 83.87% / 81.25%。命中 A 为 70.00% / 70.00% / 70.00%；B 为 66.67% / 80.00% / 72.73%。F1 上升不能覆盖新增假命中的安全失败。两臂总出手事件均33条（31条真值一对一匹配26条，额外事件7条）。', '',
'### 所有变化事件','',
'|案例|人工|A|B|解释|','|---|---|---|---|---|',
'|game01 15秒|MADE|15.22出手，16.75 MISSED|15.22出手，16.52 MADE|目标命中FN恢复|',
'|game03 56秒|MISSED|56.36出手，58.16 UNKNOWN|56.36出手，57.62 MADE|新增命中FP，否决启用|', '',
'新增负例 entered_t=56.356300，入口截止57.256300，crossing_t=57.524133，B 出口57.624233；回弹标记 false，且存在多次真实下落观测。这证明“再多等几帧/仅检查真实下降”也不能凭本例数据被宣称能区分真进与二维假穿越；本轮未搜索这类新阈值。其实际擦筐/前后掠过/篮板路径类别仍需人工逐帧核实，不由二维 trace 擅自定性。', '',
'### 三个指定已有命中 FP','',
'|人工定位|自动出手|crossing|A→B|匹配说明|','|---|---:|---:|---|---|',
'|game01 约1秒未中|2.34|3.170|MADE→MADE|仍为命中FP|',
'|game01 约170秒未中|171.67|171.938|MADE→MADE|距170秒1.67秒；仍保留协议出手FP/FN与命中FP，不放宽±1.5秒|',
'|game03 约158秒未中|159.26|160.160|MADE→MADE|仍为命中FP|', '',
'### 逐事件 A/B（31 条人工 + 7 条额外事件）','',
'原始完整事件字段见每段 `*_A_events.json`、`*_B_events.json`；以下逐条保留未匹配真值与额外事件。', '',
'|事件键|人工秒/结果|A 出手秒/结果|B 出手秒/结果|A 命中分类|B 命中分类|','|---|---|---|---|---|---|']
for r in rows:
    truth='—' if r['truth_time'] is None else f"{r['truth_time']}/{r['truth_result']}"
    av='无事件' if r['A_release'] is None else f"{r['A_release']}/{r['A_result']}"
    bv='无事件' if r['B_release'] is None else f"{r['B_release']}/{r['B_result']}"
    lines.append(f"|{r['key']}|{truth}|{av}|{bv}|{r['A_made'] or '—'}|{r['B_made'] or '—'}|")
lines += ['', '## 安全回归与启用门禁','',
'|检查|本轮结果|','|---|---|',
'|窗口专项|3个测试方法通过；两臂覆盖侧向下落、横向擦过、上升反弹、向上离开、旧穿越、全预测、预测出口、切镜、长间隔、筐失效等20个负例子场景；另有正常中心下落与延迟接近正例|',
'|投篮回归 test_shot*.py|170项通过|',
'|时间匹配 test_match_annotation_metrics.py|5项通过，容差未变|',
'|审计计数与状态守卫|5项通过|',
'|nybo贴筐负例|5项合成回归通过，原视频缺失，不能称真实视频验证|',
'|check_all.py|完整项目检查通过，日志包含逐门禁结果|',
'|31条真实基线|目标恢复但新增1个命中FP；3个指定旧FP保留：安全门禁失败|', '',
'测试日志见同目录 `window_safety.log`、`shot_regressions.log`、`matching_corrected.log`、`audit.log`、`nybo_synthetic.log`、`full_gate.log`；`test_results.json` 保留完整命令和返回码。首次时间匹配 discovery 使用了不存在的文件模式，运行0项返回5，随后改为实际测试文件并通过5项；初次日志保留，不将空跑计作通过。', '',
'合成“上升反弹”不是所有真实篮板/篮筐反弹的覆盖证明；31条缺少这些逐帧类别标注。B 既未解决原有二维穿越FP，还新增一个FP，因而**不满足“防止擦筐、从筐旁经过、篮板反弹等假MADE”的要求**。本轮不宣称已实现安全的新判定器，安全交付是拒绝 B 并保留现有默认。', '',
'## 通用穿越后窗口设计与后续边界','',
'本轮实际候选的通用定义：有效实测向下穿越建立时记录 crossing_t，验证区间 [crossing_t,crossing_t+make_window_s]；保留 entered、实测连续下降、出口范围、fresh筐、切镜/筐证据段截断与回弹约束。它不依赖比赛ID、绝对时间或人工结果，已通过配置开关离线运行。**真实负例证明仅替换窗口起点不够，不能启用。**', '',
'若后续另开实验，建议将 crossing 视为 PENDING_VALIDATION，而非同帧可自动计分：用同一筐证据段内额外真实出口观测验证，预测球不增加证据；横向逃逸、向上反弹、切镜、换筐、观测断链均中止链；过期或无法排除前后掠过则保留 UNKNOWN，不能用“未观察到回弹”直接证明命中。由于新增 game03 56秒FP本身也有多次实测下降，这一设计仍需要独立的球/筐遮挡关系或人工轨迹负例验证，不能在本轮凭空宣称会防住它。此段是未实施的后续规格，不是第二次算法实验或已通过的能力。', '',
'**启用建议：维持 make_window_from_crossing=false。** 不因命中F1上升而部署。若继续，只允许独立影子评估并先补充真实擦筐/篮板/旁路负例；目前没有独立测试来源可用于最终验收。', '',
'## 后来人工记录导入核对','',
'实际核对了原始TXT、归档TXT与规范化JSON的SHA、59条记录、对应旧JSON的时间及三段视频SHA；不是只转述旧报告。', '',
'|来源|画面记录|回放|去回放出手|视频SHA|状态|','|---|---:|---:|---:|---|---|']
for s in imports['samples']:
    lines.append(f"|{s['id']} / {s['source_id']}|{s['count']}|{s['replay']}|{s['unique']}|匹配|已单独导入 Development|")
lines += ['',
'合计59次画面记录、57次唯一出手，数据在 `eval/annotation_imports/three_bili_20261020/annotations.normalized.json`。原始归档SHA与规范化清单一致，全部时间对应既有三份人工JSON；TXT自身也声明由既有JSON导出。因此这是导入的再次提交记录，不能冒充59条新增独立人工样本，更不能将31条冻结基线冒充这些新记录。', '',
'这批记录**已在评估数据目录单独导入，但尚未纳入本轮31条冻结基线，也没有本轮自动trace和A/B结果**。本轮保持单一窗口实验，不用它们补算或改变31条指标。', '',
'已知本地三来源缺失导入清单为空。仍缺：哈登约116秒精确离手确认、完整比赛日期/对阵/源链接或源视频与当前剪辑的时间映射；哈登8条分值仍未知。这些不是漏导入整份记录。如果“后来新提供”还指这份TXT以外的另一批，请提供那批CSV/JSON/TXT原件及对应视频文件（或本地路径）、时间基准/剪辑偏移；当前可见文件不足以认定还有哪份未导入，不能编造缺失来源。', '',
'[本轮导入核对结构化结果](annotation_import_check.json)', '',
'## 变更与完整性','',
'仅新增离线实验脚本、专项安全测试和本目录报告/结果。未修改 ScoreEngine、stream 默认、模型权重、原始人工标注或冻结真值，未部署线上。工作区原有未提交修改另存到本目录 `git_status_before.txt`（如存在）与 `git_status_after.txt` 供辨认；不替他人改动做提交。保护文件前后SHA一致。', '']
save('REPORT.md','\n'.join(lines))
# Export every target frame as a compact tabular companion to full before/after JSON.
for arm in ('A','B'):
    timeline=read('target_'+arm+'_timeline.json');table=[]
    for r in timeline:
        at=r['after'] or (r['closed'][-1] if r['closed'] else None)
        if at is None or abs(at['start_t']-15.2152)>.0001:continue
        table.append(dict(frame=r['frame'],t=r['t'],entered=at['entered'],entered_t=at['entered_t'],
           entry_deadline=r.get('entry_deadline'),entry_expired=r.get('entry_expired'),crossing_t=at['crossing_t'],
           crossing_deadline=r.get('crossing_deadline'),crossing_active=r.get('crossing_active'),
           rebound=at['rim_rebound_seen'],real_obs=at['real_obs'],last_real_t=at['last_real_t'],
           left_streak=at['left_streak'],result=','.join(e['result'] for e in r['events'])))
    with (OUT/('target_'+arm+'_every_frame.csv')).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
# Verify protected files again after the full gate, not just after replay.
hashes=read('protected_hashes.json')
for filename,expected in hashes['before'].items():
    h=hashlib.sha256(Path(filename).read_bytes()).hexdigest()
    assert h==expected,filename
hashes['post_full_gate_unchanged']=True
save('protected_hashes.json',json.dumps(hashes,ensure_ascii=False,indent=2)+'\n')
print('REPORT.md generated; 38 event rows; protected hashes unchanged after full gate.')

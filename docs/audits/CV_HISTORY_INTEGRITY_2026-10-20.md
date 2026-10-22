# yuanshenwang 历史数据来源核查与修复

日期：2026-10-20。核查基于当前任务数据库、原分析文件、固定运行副本源码及本机只读API；没有代登录用户、清理任务、重算覆盖原分析或重启服务。

## 1. 核查结论

不能把登录后看到的历史列表称为`yuanshenwang`的个人历史，更不能把其中的识别结果视为经过人工核实的比赛事实。当前数据库没有账号归属字段，请求创建任务时也没有保存用户名；`_worker_owner`仅记录执行进程，不能推断账号。

| 项目 | 当前实际结果 |
| --- | --- |
| 合成任务 | 168条，均完成，是测试/演示生成数据 |
| video任务 | 22条完成、1条失败 |
| 正式默认`GET /api/jobs` | 20条，全部`source=video`；默认没有返回上述合成任务 |
| video完成任务检测记录 | 22条都有逐帧检测记录；运行过检测不等于判定准确 |
| video结果中的错误来源标签 | 52条未知事件被标记为`synthetic`，全部能匹配到`made=None`的原视觉候选 |
| 原上传文件缺失 | `e1a63bf000ad`、`0af96de3e1f6`；分析文件仍有保留 |

`source=video`也不代表正式篮球比赛：里面包括技术冒烟测试视频和开发片段。例如`114c676d56e2`的输入为`upload-analysis-smoke_91f58b67cf7bce3c.mp4`。该来源字段仅表示走过视频输入流程。

没有人工逐球、球员及战术完整真值，本次不能据检测记录证明比分、人数、号码、投篮或战术正确；也不能根据错误的来源标签断言所有视频结果都是随机生成。

## 2. 明确找到的代码问题

### 2.1 测试隔离不完整

原`tests/test_api.py::_client()`仅把账号文件放进临时目录，API的`DB_PATH`和`OUT_ROOT`仍指向项目正式`data/jobs.sqlite`及`out/`。每次完整API集成测试会生成3条合成任务并写入共享库。这是测试数据进入正式任务库的实际通路，不是普通用户上传了这些比赛。

修复：API与auth支持可选`AIHOOP_DATA_DIR`，API支持`AIHOOP_OUT_DIR`；不设置时保持原运行目录。`tests/conftest.py`在模块导入前为整个pytest会话指定临时存储，结束前等待后台线程完成再清理。独立运行`tests/test_api.py`也使用临时目录；测试helper检测到正式路径会拒绝运行。

### 2.2 没有命中证据却标成合成

`rules.fuse_outcome([])`原来返回`(None, 0, 'synthetic')`。因此真实视频的未知视觉候选在`game.timeline`里也会显示合成来源。`build_shots()`还会把未识别的先验来源默认标成合成，`Shot`构造默认来源也为合成。

修复：无证据、来源缺失均使用`unknown`；`synthetic_game()`显式写入`source='synthetic'`。保留现有事件键和结果状态，不把未知改成命中或未中。

对原52条事件进行缺证据分支的单事件重放，全部得到`result=unknown`、`source=unknown`、计分0。它不是全视频重跑，也不是准确率验证。旧分析文件未被改写。

### 2.3 页面读取失败会自动换演示结果

原`app.js`在无历史、后端不可达、任务列表或结果读取失败时自动调用`loadFromDemo()`。即使不是当前问题的唯一成因，这种切换会让用户误解数据来源。当前`web/demo/game.json`不存在，因此不能声称这次用户实际看到的全部数据来自该路径。

修复：这些情况清空旧结果并给出空状态；不自动请求演示比赛或演示战术。显式演示仍可读取，标明“合成样例，仅供界面演示”。

### 2.4 共享任务被命名为“我的任务”

修复`my.html`标题为“服务器历史任务”；首页和上传页标注所有登录用户共享；列表增加视频文件名、视频分析/导入记录/合成演示的来源标签。API新增`video_name`，不为此新增完整路径暴露。

**这不是账号隔离实现。** 旧任务归属没有被保存，不能从文件名、最后登录人或执行PID反推。真正的账号隔离需要为新任务保存创建者并检查读取/写入/媒体/WebSocket权限；旧任务应作为归属待确认的历史数据处理。

## 3. 修改文件

- `src/aihoop/api.py`：可选数据/产物目录，历史返回文件名。
- `src/aihoop/auth.py`：使用相同可选数据目录。
- `src/aihoop/model.py`、`rules.py`、`sources.py`：未知来源与显式合成来源区分。
- `.env.example`：两个可选存储配置，不改变正式默认路径。
- `tests/conftest.py`、`tests/test_api.py`：pytest和独立API测试隔离。
- `scripts/audit_history_integrity.py`：只读数据库和原产物的来源核查工具。
- `tests/test_history_integrity.py`：来源、只读核查、测试存储及历史过滤回归。
- `tests/test_history_bootstrap.js`：无任务、断网、读取失败不加载演示；真实任务和显式演示路径保留。
- `web/app.js`、`api.js`、`pages/upload.js`：移除自动演示替代，保留明确提示。
- `web/my.html`、`pages/home.js`：共享历史命名和文件名/来源展示。
- `web/index.html`：相关脚本版本更新为`100-history-integrity`。

## 4. 真实测试结果

- 初轮定向Python：44 passed，7条依赖弃用提示，4.49秒；随后增加的历史接口测试计入全量结果。
- 最终全量Python：**725 passed、15 skipped、2 failed、9 subtests passed**，24.26秒。
- 两项失败与改前上一轮全量相同：`test_multical_mini_and_snap.py::test_soft_failure_exit_carries_both_keys`、`test_plan_b.py::test_tactics_end_to_end_and_frames`。没有宣称全量通过。
- JS通过：`test_history_bootstrap.js`、`test_examples_refresh.js`、`test_results_refresh.js`、`test_shot_outcome_display.js`。
- `test_ui_home.js`仍断言已经移除的离线样例按钮存在；`test_examples.js`仍断言旧样例只读文案。两项从本轮改前源码快照复现同一失败，记录在`ui_home_before.log`、`examples_before.log`；本轮未改这些断言。
- 原数据库分组计数在测试前后完全一致：168条合成、22条video完成、1条video失败；本轮测试新增正式任务数0。
- 83份原分析文件逐个SHA复核不变；正式进程PID262365保持运行；没有部署或重启。
- 没有对`yuanshenwang`进行代登录或浏览器完整操作验收；账号没有专属任务查询可供验证，使用了服务现有的回环内部鉴权只读查询。

## 5. 证据和复现

目录：`out/history_integrity_20261020_230510/`。

- `before/`、`final_source/`：改前后脏工作区源码快照与文件清单，包含此前未提交工作，不是纯净Git版本。
- `inventory_before.json`：23条非合成任务来源、83份文件身份、错误来源标签及归属缺失情况。
- `live_history_readonly.json`：正式默认历史接口的20个ID及来源汇总。
- `source_label_replay.json`：52条未知事件的来源标签分支重放。
- `storage_isolation_verified.json`：测试前后正式库计数和原文件保护检查。
- `regression.log`、`targeted.log`、`js_checks.json`：实际测试结果。

```bash
cd /data/projects/ai-basketball-analyst
export PYTHONPATH=src:scripts
export PATH=/data/projects/ai-basketball-analyst/out/cv_baseline_20261015/tools:$PATH

# 只读核查，输出文件须不存在
/data/conda-envs/ai-basketball-analyst/bin/python scripts/audit_history_integrity.py \
  --database data/jobs.sqlite --out out/history_inventory_recheck_01.json

# pytest自动选择临时任务/账号/产物存储
/data/conda-envs/ai-basketball-analyst/bin/python -m pytest \
  tests/test_history_integrity.py tests/test_api.py tests/test_shot_auth.py -q
node tests/test_history_bootstrap.js
node tests/test_examples_refresh.js
node tests/test_results_refresh.js
```

## 6. 当前状态和下一步

本轮修复已经落在开发源码，正式固定副本和既有分析保持原样，所以正式网站不会因本次源码修改立即变化。未删除168条合成数据，未把旧未知事件强行改成已确认结果。

建议下一步优先完成新任务创建者记录和全路径访问权限，再审慎处理旧共享历史及技术测试记录的展示。识别准确性应继续使用用户审核的原视频事件验证，不能通过修改来源标签证明算法准确率改善。

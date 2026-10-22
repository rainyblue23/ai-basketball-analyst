# 正式站结果文字修复：已发布与验收

日期：2026-10-21。状态：**用户已授权发布和重启；正式副本已切换，登录后的正式页面已验收**。

验收时间：2026-10-21 19:34（Asia/Shanghai）；正式服务PID465726，运行副本`deploy/runtime/20261021-result-ui`。

## 截图根因

用户截图对应新任务`097c0611d8c3`，包含约6.4、15.0、19.9、21.7、31.0、46.0、64.1、74.8、85.0秒9条记录。正式进程PID262365的`PYTHONPATH`仍指向`deploy/runtime/20261016-152930/src`，静态页面也由该固定副本提供。

此前只修了开发工作区和本机预览，没有更新正式服务，因此用户仍看到旧“未知”结果徽章和无条件显示的分值。不是要求用户重新上传才能解决的问题。

原任务有2条MADE、7条UNKNOWN。新的页面只把已有结果显示为“中／没中”，另7个时间点保留回看入口；不把它们默认算成没中，也不直接采纳未确认建议。没有可靠分值的行不显示“分值未知”或假定分数。

## 可发布副本

`deploy/runtime/20261021-result-ui/`从当前正式副本复制，仅更新7个前端文件：

- `web/data.js`
- `web/pages/overview.js`
- `web/pages/review.js`
- `web/pages/highlights.js`
- `web/detection-overlay.js`
- `web/components.js`
- `web/index.html`

`src/`和`scripts/`与当前正式副本逐文件哈希相同。没有把工作区未验收的CV改动带入发布副本。原副本未改；数据、产物、模型沿用原存储，没有重算覆盖。新JS使用缓存版本`103-result-ui-release`。

## 验证

- 候选副本中的实际JS通过5项定向测试：二态标签、分值显示、人工复核、播放器、结果刷新。
- 使用截图对应任务的保存数据，在实际Vue总览组件中浏览器验证：2个“中”结果、7个仅时间的回看入口，9个原时间点都保留；列表无“未知／推测／暂定／分值未知”文字；未中筛选及原事件定位通过。
- 原事件JSON和比分逐字不变，没有外部或写入请求。
- 发布前检查没有queued/running任务；正式服务已切换并重启，健康检查返回200、`ok=true`。
- 使用临时账号登录`https://basketparts.top/web/index.html#/overview`，通过实际`APP_LOAD_JOB`加载任务`097c0611d8c3`：2条“中”、7个其他回看时间，9个原时间点全部保留。公开站HTML版本为103，6个更新的JS资源使用`103-result-ui-release`。
- 正式页面没有结果“未知／推测／暂定”和“分值未知”；已有事件及比分在浏览器中保持一致。保存的`game.json` SHA仍为`5918dc3d45d31060b6feb74964084c204ce3525cb5a142268a74bb752bc542a7`。
- 临时账号和其会话已清理；原账号文件SHA完全一致。浏览器仅调用登录/退出写接口，没有分析、纠错或结果写入；Cloudflare另有`/cdn-cgi/rum`遥测POST。
- 新旧副本清单均复核通过，旧副本未修改；后端和脚本哈希完全相同，`AIHOOP_DISABLE_SCOREBOARD_FUSION=1`保持禁用。
- 本次没有跑模型，不代表底层识别准确率已提升。

证据：`out/result_ui_release_20261021_01/`，包括发布清单、输入SHA、测试日志、浏览器截图和只读验证。

本机预览：`http://127.0.0.1:8140/`。

## 发布过程与回退

用户此前在“第二阶段第一部分／任务五”要求“不要部署或重启正式服务”，本轮已明确回复“允许发布并重启”，因此执行发布。

使用`activate_release.py --apply`先校验源码身份和无分析任务，再新增独立`95-result-ui.conf`，切换副本并重启。现有`70-pinned-runtime.conf`保持原样，数据和网页登录会话沿用原存储。

第一次切换因继承的`ExecStartPre`仍执行旧副本的校验器，触发“Attempt loaded from a different source tree”；脚本自动移除新覆盖配置并恢复旧站。随后清空继承的`ExecStartPre`列表，改为运行新副本中的同一份校验脚本，保留原校验逻辑；增加重启前的同源预检。预检通过后第二次切换成功。没有关闭启动校验。

```bash
cd /data/projects/ai-basketball-analyst

# 只读核对源码身份、契约和空闲状态
/data/conda-envs/ai-basketball-analyst/bin/python \
  out/result_ui_release_20261021_01/activate_release.py

# 如需回退，脚本先检查没有分析任务
/data/conda-envs/ai-basketball-analyst/bin/python \
  out/result_ui_release_20261021_01/activate_release.py --rollback
```

`--apply`本轮已成功执行，不需要重复发布或重新分析用户视频。

## 验收证据和范围

- `out/result_ui_release_20261021_01/release.json`：实际发布状态、修改文件、运行副本。
- `activation.json`：成功切换记录。
- `final_verification.json`：源码身份、服务健康、原任务SHA和账号清理核对。
- `js_checks.json`及5份日志：定向JS测试全部通过。
- `public_browser_verified_final/checks.json`：真实域名、登录后页面、资源版本、事件及比分不变断言。
- `public_browser_verified_final/production_results.png`：正式站结果卡片截图。
- `verification_cleanup_retry.json`：临时账号清理和原账号文件SHA核对。

首次浏览器验收脚本有未包裹的异步表达式，修正后重新执行；第二次把Cloudflare遥测误判为业务写入，改为逐条保存请求并核对`/api/`写请求，最终通过。两次失败均为验收脚本问题，临时账号也均已清理。

本次是界面发布，不是CV模型或投篮算法升级；7条证据不足的记录只保留回看时间，未伪造为没中，原始未知数据仍保留在JSON中。未重跑完整Python回归，不宣称整体测试或识别准确率提升。

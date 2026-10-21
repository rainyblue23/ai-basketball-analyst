# DATASET IDENTITY AUDIT

日期：2026-10-20。只读核查，未修改预期SHA或真值。

|样本|SHA一致|条目|用途|来源身份|
|---|---|---:|---|---|
|s2_fixedcam_7shots|True|7|Development|pending|
|s2_hs_game01|True|14|Development|pending|
|s2_hs_game03|True|10|Validation_exposed|pending|
|match_01|False|3|Quarantined|pending|
|match_02|False|0|Quarantined|pending|
|match_03|False|0|Quarantined|pending|
|match_04|False|1|Quarantined|pending|
|yang|True|10|Development|pending_full_match_identity|
|lillard|True|15|Development|pending_full_match_identity|
|harden|True|34|Development|pending_full_match_identity|

## 四段历史测试集

4段均存在但字节哈希不符；对samples下所有视频按SHA搜索，匹配位置见identity_manifest.json。纯重命名不会改变SHA，不能单独解释差异。
当前没有旧文件、旧解码帧摘要或逐包摘要，不能判定是转码、重封装、裁剪、替换错误源还是内容变化。全部继续隔离。
本地_videofind/finalize_pro.ps1记录过ACB重编码及素材重命名；pro_sources.json的早期WNBA来源指向后来被README纠正的错误节目。它们证明历史有变更风险，不能证明本次SHA差异的具体原因。
eval/ball_feedback_validation.md明确：match_01/02用于训练，match_03/04用于验证和诊断。因此恢复旧SHA也不能使这四段成为独立测试。

## 来源与时间

原标注没有source_match_id。manifest另存provisional source_group_key，不能把文件名或不同BV号直接当作不同比赛的证据。
同一源字节重复件已分组；同比赛的不同转码/剪辑不能靠SHA自动证明，需比赛日期/对阵/场次及原片出处确认后合并来源组。
31条真值的时间指向当前4分钟素材或训练短片，不是已恢复的整场原片时间。原片剪辑偏移保持pending。审核完整性仅有用户声明，未重新标注。
game03已经在历史报告公开评估过，记Validation_exposed；只能做跨来源回归，不能当未见过的锁定测试。
三段Bili为Development，59次画面出现、57次去回放出手；全部有视频SHA，来源分组采用BV号，完整比赛身份仍pending。

## 恢复条件

找回冻结原文件或带哈希的备份；比较解码帧/音频时间对应，建立可复现的时间映射。若确认内容或裁剪改变，则新建数据版本并重新人工审核，禁止改旧预期SHA。
新Independent Test需按真实比赛来源隔离、未训练未诊断、完整审核区间、锁定视频SHA/时间偏移/回放关系。当前锁定Independent Test为0。

[逐视频SHA、媒体元数据与来源清单](out/stage2_audit_20261020/identity_manifest.json)

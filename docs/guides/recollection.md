# 追忆战场任务

GUI 和命令行使用同一套任务。需要能连接游戏的设备配置；当前实机识别范围为国服雷电 960×540。入口、日程表选项与游戏规则见[游戏知识](../game-knowledge/recollection.md)。

| 任务 | 注册名 | 范围 |
|---|---|---|
| 追忆战场首通 | `recollection_first_clear` | 推进普通记忆领域及已解锁霸领域；自动取得当前层攻略并核验编队，按通关印章确认进展。 |
| 追忆战场日常 | `recollection` | 领取普通累计报酬，使用现有次数与扫荡券扫荡已通关霸领域。不会推进首通。 |

日程表可领取普通报酬，但霸设置只显示剩余次数。新工程默认日常已加入 `recollection`；已有配置需在 GUI 添加该任务，或在 `Task` 列表添加 `[recollection]`。如果日程表已领完普通报酬，日常任务会检查空宝箱后继续。

## 运行与配置

GUI 在“按需专项”运行追忆战场首通，在“每日日常”添加或单独执行追忆战场日常。命令行从项目根目录运行：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py recollection_first_clear --config daily_config.yml
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py recollection --config daily_config.yml
```

两任务不使用位置参数；分别读取 YAML 中的 `RecollectionFirstClear`、`Recollection`。省略字段时采用下列默认值，完整默认配置见 [runtime_defaults.yml](../../runtime_defaults.yml)。

```yaml
RecollectionFirstClear:
  areas: [记忆领域, 霸瞳皇帝的领域, 泽恩的领域, 米洛克的领域]
  timeout: 3600
  battle_timeout: 220
  max_battles: 30
  max_attempts_per_stage: 2
  source_urls: []
  discover_sources: true
  allow_local_trials: false
  auto_equip: false
  sources: {}
Recollection:
  areas: [霸瞳皇帝的领域, 泽恩的领域, 米洛克的领域]
  timeout: 600
  claim_rewards: true
  sweep_dominion: true
  max_sweeps: 9
  preview_only: false
```

`areas` 可缩小范围，例如首通只填 `[记忆领域]`。日常的领域列表只控制霸的扫荡；普通报酬由 `claim_rewards` 独立控制。`max_sweeps` 是本次所有领域合计次数，同时受游戏当前剩余次数和券余额限制；不是每领域上限，也不保证一次清完。首通的 `max_battles` 限制总战斗数，`max_attempts_per_stage` 限制每层候选尝试数。锁定领域保留原因，次数用完就停止该领域，不自动重置。

日常设置 `preview_only: true` 可检查报酬状态、勾选和最终扫荡确认，随后取消；不会新领取或新提交扫荡。存在上次待核对消费时仍先按实际余额复核，不能用预览模式绕过恢复检查。扫荡会花掉首通可用的本周霸次数，需要推进首通时先运行首通任务。

## 攻略与开战条件

程序自行搜索来源、获取视频、建立公共头像索引、解析和更新缓存，不要求 Agent 下载头像或准备作业。优先攻略链接填在 `RecollectionFirstClear.source_urls`；其余搜索参数放 `sources`。参见[共享解析边界](../video-strategies.md)。

普通搜索未找到可执行作业时，`sources.search_effort: high` 扩大查询与元数据核验范围，优先具体层数和较新来源，也搜索“追忆的战场 AUTO／全制霸参考”等标题。长合集的目标层可能超出默认 180 秒解析范围；可按需要提高 `sources.max_video_seconds` 与 `sources.max_frames_per_page`，仍受任务及解析总时限约束。搜索加强不会放宽开战条件。

来源必须明确对应领域和单层，五人身份、衣装、等级、Rank、星数、技能、专武 1/2、五个 SET 与固定 AUTO 开关均有证据，且服区匹配。程序保留来源的 AUTO 开启或关闭设置，不支持战斗中切换或手动轴。合集可以作为候选，不能把“9～12层”当成第 9 层队伍；有特别装备、全局培养或手动轴等未支持要求时停止。账号当前培养不补写为来源要求。

`allow_local_trials: true` 明确允许按账号培养试打培养字段不完整的来源，仍须知道当前层、服区、五人和 SET/AUTO，且每人的实时培养与专武状态都读清。无可靠专武徽标时由人物页核验是否尚未实装专武，返回后重新选择五人；开战前只读核对每人的特别装备槽位。未知身份、装备或其他必要条件继续阻止开战；报告保留缺失字段、空槽和账号观察。默认关闭，不自动强化角色或专武、不购买体力、不重置次数或进度。

`auto_equip: true` 可在五人核验通过、槽位已读清且存在空槽时，使用游戏保存的自动装备设置分配现有特别装备，核对提交后的槽位再开战。游戏可能取用其他角色的装备；默认关闭。此选项不能代替来源指定装备或全局培养要求的核验。

## 结果与恢复

运行记录位于 `cache/daily/runs/<run>/tasks/<序号>-<任务名>/`，包括任务报告及预览、编队、战后证据。首通的每次挑战独立保存在 `battle_<标识>/`，后续选人不会覆盖前一场的角色和战斗设置证据。`complete` 表示本次核对目标完成，`already_complete` 表示无需动作；`partial` 或 `blocked` 的 `pending` 说明未完成原因，不能当成全部首通完成。

两任务共用 `cache/daily/recollection_state/` 的待核对记录，提交前保存，提交后核对通关印章、领域次数或券余额，再清除。回执未知时不重放消费；重跑先核对实际结果，无法核对则保留现场和记录。切换账号时，为两配置段填写相同的 `account_key`，不同账号用不同值；默认按设备隔离。

首通恢复到已知失败结算页时，先保存失败证据并返回原层，只有未通关标记和未减少的次数一致才解除待核对状态；本次恢复会跳过刚失败的同一来源队伍，继续其他候选。没有失败证据的未通关状态不能单独授权重试。

实机消费回执、连续首通及空缓存完整攻略链路的未完成验收见[工程待办](../pending-validation.md)。暂停或停止须等待状态确认后才能检查设备，见[运行诊断](../run-diagnostics.md)。

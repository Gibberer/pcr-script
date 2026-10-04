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
  max_source_batches: 3
  source_urls: []
  discover_sources: true
  allow_local_trials: false
  auto_equip: false
  auto_equip_priorities: {}
  retry_failed_parties: false
  mastery_preparation: {}
  sources: {}
Recollection:
  areas: [霸瞳皇帝的领域, 泽恩的领域, 米洛克的领域]
  timeout: 600
  claim_rewards: true
  sweep_dominion: true
  max_sweeps: 9
  preview_only: false
```

`areas` 可缩小范围，例如首通只填 `[记忆领域]`。日常的领域列表只控制霸的扫荡；普通报酬由 `claim_rewards` 独立控制。`max_sweeps` 是本次所有领域合计次数，同时受游戏当前剩余次数和券余额限制；不是每领域上限，也不保证一次清完。首通的 `max_battles` 限制总战斗数，`max_attempts_per_stage` 限制每层实际开战数；缺员或装备不明的战前核验不计入开战次数。`max_source_batches` 限制每层来源批次，已检查的来源不会在后续批次重复解析。锁定领域保留原因，次数用完就停止该领域，不自动重置。

日常设置 `preview_only: true` 可检查报酬状态、勾选和最终扫荡确认，随后取消；不会新领取或新提交扫荡。存在上次待核对消费时仍先按实际余额复核，不能用预览模式绕过恢复检查。扫荡会花掉首通可用的本周霸次数，需要推进首通时先运行首通任务。

## 攻略与开战条件

程序自行搜索来源、获取视频、建立公共头像索引、解析和更新缓存，不要求 Agent 下载头像或准备作业。优先攻略链接填在 `RecollectionFirstClear.source_urls`；其余搜索参数放 `sources`。参见[共享解析边界](../video-strategies.md)。

普通搜索未找到可执行作业时，`sources.search_effort: high` 扩大查询与元数据核验范围，优先具体层数和较新来源，也搜索“追忆的战场 AUTO／全制霸参考”等标题。长合集的目标层可能超出默认 180 秒解析范围；可按需要提高 `sources.max_video_seconds` 与 `sources.max_frames_per_page`，仍受任务及解析总时限约束。搜索加强不会放宽开战条件。

来源必须明确对应领域和单层，五人身份、衣装、等级、Rank、星数、技能、专武 1/2、五个 SET 与固定 AUTO 开关均有证据，且服区匹配。程序保留来源的 AUTO 开启或关闭设置，不支持战斗中切换或手动轴。合集可以作为候选，不能把“9～12层”当成第 9 层队伍；有特别装备、全局培养或手动轴等未支持要求时停止。账号当前培养不补写为来源要求。

`allow_local_trials: true` 明确允许按账号培养试打培养字段不完整的来源，仍须知道当前层、服区、五人和 SET/AUTO，且每人的实时培养与专武状态都读清。无可靠专武徽标时由人物页核验是否尚未实装专武，返回后重新选择五人；开战前只读核对每人的特别装备槽位。未知身份、装备或其他必要条件继续阻止开战；报告保留缺失字段、空槽和账号观察。默认关闭，不自动强化角色或专武、不购买体力、不重置次数或进度。

账号试打只补足来源未给出的字段；已声明的等级、Rank、星数、技能、专武开关及强化数值仍须满足，冲突声明不能放行。头像确认身份后仍读取缺失的技能等级；同一次任务可复用近期的完整技能核验。

攻略指定专武等级或强化阶段、编队徽标只能确认开关时，程序转到人物页只读核对数值，再返回重新选择五人。已有明确缺员的队伍直接继续后续来源，避免不能补齐队伍的装备往返；不会自动安装或训练专武。

`auto_equip: true` 可在五人核验通过、槽位已读清时，使用游戏保存的自动装备设置重新分配现有特别装备，再核对提交后的槽位。已填满的槽位也会检查分配，避免沿用之前队伍的装备；无变化时取消预览。游戏可能取用其他角色的装备；默认关闭。此选项不能代替来源指定装备或全局培养要求的核验。

可用 `auto_equip_priorities: {armor: magic_defense, accessory: hp}` 显式设置防具优先魔法防御、饰品优先生命值；需要同时开启 `auto_equip`。类别为 `weapon`、`armor`、`accessory`，属性为 `rarity`、`skill`、`physical_attack`、`magic_attack`、`physical_defense`、`magic_defense`、`hp`、`physical_critical`、`magic_critical`、`physical_penetration` 或 `magic_penetration`。省略的类别沿用游戏设置。程序核对选中状态及返回页的属性回显后才预览装备；未知选项或回显冲突取消并停止。这只调整现有装备的分配，不训练装备，也不保证某套优先级能通关。

开启 `allow_local_trials` 时，直接从战斗开始的视频可通过首领全名、等级、生命上限和计时，与程序刚读取的当前层详情对应。必须保留两侧画面证据并取得至少两帧完整五人及固定 SET/AUTO；其他层或冲突范围不会归入当前层。该候选保留账号试打标记，培养与装备仍逐人核验。

## 结果与恢复

首通战斗每两秒至多保存一份可识别的倒计时、首领生命值与头像状态，报告中的 `samples` 链接到原图。已读取现场生命上限时，战斗 OCR 的上限须与它一致，截断或冲突数字记为未知。头像与可见生命条共同记录存活和减员线索；遮挡或闪光没有完整生命条时保留未知，不能把未识别到倒下角色当作五人存活。这些诊断记录不能代替通关印章、消费核对或授权同队重试。

运行记录位于 `cache/daily/runs/<run>/tasks/<序号>-<任务名>/`，包括任务报告及预览、编队、战后证据。首通的每次挑战独立保存在 `battle_<标识>/`，后续选人不会覆盖前一场的角色和战斗设置证据。`complete` 表示本次核对目标完成，`already_complete` 表示无需动作；`partial` 或 `blocked` 的 `pending` 说明未完成原因，不能当成全部首通完成。

两任务共用 `cache/daily/recollection_state/` 的待核对记录，提交前保存，提交后核对通关印章、领域次数或券余额，再清除。回执未知时不重放消费；重跑先核对实际结果，无法核对则保留现场和记录。关闭 `claim_rewards`、`sweep_dominion` 或开启 `preview_only` 只控制新动作，已有领奖、扫荡记录仍须核对；无法确认时停止，不报告完成。切换账号时，为两配置段填写相同的 `account_key`，不同账号用不同值；默认按设备隔离。

霸扫荡的击破汇总会先与待核对记录中的每关次数和关卡数比较，保存后才确认退出；随后继续结算并核对各领域次数及券余额。汇总不符或缺少对应记录时停止，不能把背景卡片当作本次目标，也不会再次提交扫荡。

首通恢复到已知失败结算页时，先保存失败证据并返回原层，只有未通关标记和未减少的次数一致才解除待核对状态；本次恢复会跳过刚失败的同一来源队伍，继续其他候选。没有失败证据的未通关状态不能单独授权重试。

首通默认跨运行跳过已核验失败、条件未变化的队伍。比较当前层首领、五人的实时培养、编队战力、特别装备外观及 AUTO/SET；开启精通准备时也比较本次重新读取的完整职能节点等级与属性，培养变化即使未反映到编队战力也可重新试打。每次仍重新核验当前账号，缓存不能授权开战。只有战斗设置与战后标记、次数都已核对的失败或明确减员撤退才留作去重依据，未知回执、设置失败或缺少完整观察不计入。旧失败记录没有精通观察时，不能把新增观察本身当成培养变化；明确重试需设置 `retry_failed_parties: true`，其余战前条件和次数上限仍生效。

## 可选职能精通准备

显式配置 `mastery_preparation` 后，首通任务会先用现有材料提升指定职能的四个节点，再重新核验战斗队伍。默认 `{}` 不执行培养。当前支持 `attack`（攻击）、`break`（破防）、`buff`（增益）、`speed`（强化）和 `defense`（坦克），目标为 Lv3；已达到更高等级的节点跳过，Lv1 流程尚未核验时停止。

```yaml
RecollectionFirstClear:
  mastery_preparation:
    roles: {break: 3, buff: 3, speed: 3, defense: 3}
    max_tickets: 0
    max_actions: 150
    strengthen_target_level: false
    node_order: {}
    claim_earned_rewards: false
```

`max_tickets` 限制本次补材料所用的现有精通券，默认 0；材料不足时才按页面显示批量抽取，每批最多 500 张，最后不足 500 张时须核对实际消耗。按钮消耗超过剩余上限、余额为零或未知时停止，不购买券。`max_actions` 合计限制强化、升级和抽取的次数。程序先让全部指定节点达到 Lv3，再执行可选强化，避免转换材料被提前用完。`strengthen_target_level: true` 会继续使用现有材料强化 Lv3，遇到材料不足或可升到 Lv4 时停止；不会为了这部分可选强化追加抽取。

`node_order` 可为指定职能设置节点顺序，须完整列出 `[0, 1, 2, 3]` 的一种排列，编号按页面左上、右上、左下、右下。默认按页面顺序；例如 `node_order: {speed: [3, 0, 2, 1]}` 优先强化技能值充能。它仍先完成全部必需等级；有限的共用材料按职能配置及节点顺序用于可选强化。

`claim_earned_rewards: true` 在准备开始和必需等级完成后检查强化任务，免费领取已经达成的奖励，再读取节点的实际材料；默认关闭。领取前保存待核对记录，回执持久化后才关闭；中断后先复核原回执或已保存回执对应的任务页，不重新提交未核对的领取。未知页面保持停止。

每次消费前保存记录，强化后核对节点名称、等级及属性，抽取后核对券余额。重跑先解决未核对消费，无法确认时保留记录并停止，不重复提交。精通培养影响同职能角色，不代表已满足某个攻略的所有全局要求，也不保证通关。任务随后仍重新读取实际五人与装备，按原首通条件开战。

实机消费回执、连续首通及空缓存完整攻略链路的未完成验收见[工程待办](../pending-validation.md)。暂停或停止须等待状态确认后才能检查设备，见[运行诊断](../run-diagnostics.md)。

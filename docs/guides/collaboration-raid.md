# 联动讨伐

GUI 添加“活动日常”，在 `Activities.types` 中启用 `collaboration_raid` 类型。配置段继续兼容 `CollaborationRaid`，也可用 `Activities.options.collaboration_raid` 覆盖。统一注册名为 `campaign_clean`；旧 `collaboration_raid` 命令只作兼容，见[活动日常](activities.md)。

当前支持国服「僵尸乐园连结！Re:DIEve」及首领「佐贺陶洛斯」。其他活动身份或页面不符时停止，需另行适配。

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py campaign_clean --config daily_config.yml
```

任务核对本期活动、完整开放时间和讨伐券，按普通、困难、高难顺序检查首通。未首通时仅在画面明确显示首次讨伐免费后尝试，从程序自动搜索或 `source_urls` 指定的攻略获取五人及固定 SET/AUTO，再核对账号角色、培养和装备。默认允许在免费首通中按已核验账号培养试打；来源缺失字段仍保留未知，明确的必要要求必须满足。缺角、身份不明、未解析的手动操作或装备条件会阻止开战。

高难首通确认后使用现有讨伐券；默认本次最多消耗 99 张讨伐券。领取已达成任务奖励，并自动兑换已有讨伐奖励券，默认最多 200 批；每批按画面显示的消费与兑换后余额核账。仅当目标报酬和普通报酬均已抽空时切换奖池。不购买券、体力或次数，不重置首领进度，也不强化专武。

可在 YAML 中调整：

```yaml
CollaborationRaid:
  first_clear: true
  allow_local_trials: true
  discover_sources: true
  source_urls: []
  auto_equip: false
  max_battles: 6
  max_tickets: 99
  claim_rewards: true
  exchange: true
  max_exchange_batches: 200
  timeout: 5400
  battle_timeout: 240
```

游戏「报酬交换 → 便利设定」选为一键交换时，任务使用该按钮及其显示的张数，不退回逐次兑换；一键交换确认窗口尚未适配，遇到时保留待核对记录并停止。只处理已通关日常时设 `first_clear: false`；保留奖励券时设 `exchange: false`。`max_battles` 限制本次免费首通尝试，达到预算或不明确的页面会保留现场。角色特别装备只在 `auto_equip: true` 时安装现有可用装备，缺失时不购买。

多账号共用设备时，为每个账号设置不同的 `account_key`，隔离待核账记录；默认按设备区分。

业务报告与截图位于运行记录的 `tasks/<序号>-collaboration_raid/`。`complete` 表示首通、跳过、领奖和兑换均已核账；因 `max_tickets` 留下的讨伐券以 `budget_limited` 标记，不阻止后续活动类型。阵容或回执受阻会报告 `partial` / `blocked`。中断后的未核账消费不会重复提交，需先核对原回执与余额。当前实机验收范围见[工程待办](../pending-validation.md)，游戏页面与规则见[联动讨伐知识](../game-knowledge/collaboration-raid.md)。

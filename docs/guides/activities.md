# 活动日常

GUI 添加“活动日常”，或运行通用 CLI 的 `campaign_clean`，一次处理已启用的活动类型。新默认日常只保留这一项；旧注册名继续兼容。

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py campaign_clean --config daily_config.yml
```

```yaml
Activities:
  types: [collaboration_raid, revival, story]
  options:
    collaboration_raid:
      max_tickets: 5
      max_exchange_batches: 200
    story:
      first_clear: false
Task:
  1:
    - [campaign_clean, true, false]
```

`types` 是本次依次处理的类型，可以删减或调整顺序；空列表不操作游戏。`options` 按类型覆盖原有配置段，未覆盖的值继续来自 `CollaborationRaid`、`RevivalEvent`、`StoryEvent`。不同类型不共享来源、首通开关或消费预算。两个旧位置参数仍只控制剧情活动的困难扫荡和剩余体力扫荡。

| 类型 | 适用范围与消费 |
|---|---|
| `collaboration_raid` | 联动讨伐：程序核实专属入口、活动身份与完整开放时间；免费首通后使用现有讨伐券跳过，领奖并兑换已有奖励券。默认最多99张讨伐券、200批兑换，奖池两类报酬全部抽空才切换。[详细说明](collaboration-raid.md)。 |
| `revival` | 复刻活动：独立查询开放日程，按活动身份和完成记录接续。保留独立的首通、体力及阵容检查。[详细说明](story-event.md#复刻活动)。 |
| `story` | 剧情活动：先按本地日程筛选，再核实游戏入口，处理已通关关卡扫荡、剧情、领奖与兑换。首通和首领默认关闭，体力范围沿用剧情活动设置。[详细说明](story-event.md)。 |

同期开启的活动会分别处理，不用单一“当前活动”相互覆盖。[静态数据库](database.md)直接从游戏资源服务器更新，包含联动讨伐的独立日程。程序先跳过未开放类型，再核实游戏专属入口、身份和完整时间；未知活动或界面不会按已有活动执行。更新无需启动游戏或开启 root。

某类型报告 `partial`、`blocked` 或错误时，统一入口保留现场并停止后续类型；已完成类型的结果仍保存在报告中。先解决未核账原因，再接续即可。每个类型的证据位于本次运行目录下的独立子目录，汇总报告位于父目录。

旧配置的 `collaboration_raid`、`revival_event_once` 可继续单独执行，GUI 仅将它们作为旧配置兼容项保留，不作为新增任务显示。完整日常列表同时存在 `campaign_clean` 和对应独立入口时，只执行统一入口覆盖的类型一次；未启用的类型仍可由旧入口单独处理。多个 `campaign_clean` 行仍表示显式重复运行。

旧的 `scripts/daily/story_event.py --only missions` 等单步骤命令仍只处理剧情活动；`clear_campaign_first_time` 仍只显式启用剧情活动首通。

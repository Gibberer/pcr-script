# 剧情活动与复刻活动

列表式剧情活动的重复日任务为 `campaign_clean`，地图式复刻的一次性任务为 `revival_event_once`。GUI 可在“每日日常”或“按需专项”中选择；命令行入口分别为：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/story_event.py
./.venv/Scripts/python.exe -X utf8 scripts/daily/revival_event.py
```

## 剧情活动日常

`campaign_clean` 默认处理已通关关卡的困难批量扫荡、可选普通扫荡、可领奖剧情与活动任务、活动券兑换。首通及未通首领默认关闭；仅在新活动中确认目标、来源和队伍后启用。体力不足时停止追加扫荡，继续处理可领奖内容；不会购买体力或重置次数。

配置示例：

```yaml
StoryEvent:
  first_clear: false
  bosses: false
  stories: true
  memoirs: true
  missions: true
  exchange: true
Task:
  1:
    - [campaign_clean, true, false]
```

任务的两个位置参数分别控制困难扫荡与剩余体力的普通扫荡。需要单独处理一项时，可为独立入口指定 `--only stories|memoirs|missions|sweep|exchange`。游戏页面与当期关卡规则见[剧情活动知识](../game-knowledge/story-events.md)。

## 复刻活动

`revival_event_once` 根据当前活动身份处理关卡、首领、剧情、任务和讨伐证兑换。已完整完成的同一活动再次运行会跳过；未完成时保留原因供接续。账号切换后应设置不同的 `RevivalEvent.account_key`，避免复用其他账号的完成记录。活动身份不决定页面布局，未知的新布局会保留现场并停止。

高难与 SP 仅使用匹配当前活动、难度和模式的来源队伍，开战前检查角色身份与培养要求。队伍缺失或条件未知时不套用旧活动方案。战斗中减员、超时或无法确认结果有停止边界；不会点击会重置整场首领进度的“放弃”。[复刻游戏知识](../game-knowledge/revival-events.md)记录已观察到的地图与奖励规则。

## 结果与限制

运行记录保存在本地 `cache/daily/runs/`，查看每项完成状态及未完成原因。胜利动画不等于首通，任务须核对实际关卡/首领标记。当前实机验证覆盖雷电 960×540；新活动首通和新复刻布局仍需自然状态验证。视频攻略解析范围见[技术说明](../video-strategies.md)。

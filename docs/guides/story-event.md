# 剧情活动与复刻活动

列表式剧情活动的重复日任务为 `campaign_clean`，地图式复刻的一次性任务为 `revival_event_once`。GUI 可在“每日日常”或“按需专项”中选择；命令行入口分别为：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/story_event.py
./.venv/Scripts/python.exe -X utf8 scripts/daily/revival_event.py
```

## 剧情活动日常

`campaign_clean` 默认处理已通关关卡的困难批量扫荡、可选普通扫荡、可领奖剧情与活动任务、活动券兑换。首通及未通首领默认关闭；首通需准备保存队伍并设置体力上限，高难首领另须核对本期来源和队伍条件。体力不足时停止追加扫荡，继续处理可领奖内容；不会购买体力或重置次数。

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

启用 `StoryEvent.first_clear` 并明确设置 `allow_local_trials: true` 后，列表式活动首通使用游戏内「自动推进」：核对保存的五人身份和装备，读取推进终点与最高体力消耗，确认「立即发动」后开始。`max_first_clear_stamina` 默认 200，限制本次任务的首通体力；`first_clear_timeout` 默认 900 秒，限制每段自动推进等待。体力不足、队伍未知、进度未增加或非预期中断会停止，不购买体力。首通结束重新扫描关卡与终点，已通关时跳过。

memoirs 控制已适配的附加剧情，包括「复制世界回忆录」及「小沙月敬启」特别章节。首次教学和登录奖励先于首页识别处理。首领仍由 `bosses` 独立控制；活动情报落后时，程序可从当前活动首页核对举办时间，并将首页艺术字标题与帮助页普通字体标题交叉核对，再按当前难度和模式搜索来源。

单独选择 GUI 的「活动首通」或执行 `scripts/daily/task.py clear_campaign_first_time`，会为本次调用启用首通，并沿用上述队伍、预算、首领及领奖配置，不修改日常配置。

## 复刻活动

`revival_event_once` 根据当前活动身份处理关卡、首领、剧情、任务和讨伐证兑换。已完整完成的同一活动再次运行会跳过；未完成时保留原因供接续。账号切换后应设置不同的 `RevivalEvent.account_key`，避免复用其他账号的完成记录。活动身份不决定页面布局，未知的新布局会保留现场并停止。

高难与 SP 仅使用匹配当前活动、难度和模式的来源队伍，开战前检查角色身份与培养要求。队伍缺失或条件未知时不套用旧活动方案。战斗中减员、超时或无法确认结果有停止边界；不会点击会重置整场首领进度的“放弃”。[复刻游戏知识](../game-knowledge/revival-events.md)记录已观察到的地图与奖励规则。

## 结果与限制

运行记录保存在本地 `cache/daily/runs/`，查看每项完成状态及未完成原因。胜利动画不等于首通，任务须核对实际关卡/首领标记。当前实机验证覆盖雷电模拟器 960×540；首次教学、普通/困难首通和剧本首领已分段实测；无中途接管的冷缓存完整首日流程及新复刻布局仍需自然状态验证。视频攻略解析范围见[技术说明](../video-strategies.md)。

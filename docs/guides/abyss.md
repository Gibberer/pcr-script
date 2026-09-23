# 深域关卡推进

按需任务 `abyss_push`；GUI 入口为“按需专项 → 深域关卡”，命令行为：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py abyss_push
```

任务按火、水、风、光、暗的顺序定位地图 NEXT，读取关卡详情，获取适用来源并核对当前账号的角色身份和培养。完整来源要求不明时不会把账号现状当成攻略要求。本地试打需要显式开启 `Abyss.allow_local_trials`（默认关闭）；试打队伍和有来源的队伍会分别标记。

```yaml
Abyss:
  source_urls: []
  allow_local_trials: false
  max_failures_per_stage: 6
  max_repeat_failures_per_stage: 2
  max_battles: 30
  allow_five_star_upgrade: false
  allow_divine_amulets: false
```

可在 `source_urls` 填写本任务优先攻略链接；为空时会自动搜索。公共头像索引和已支持的视频布局由程序准备和解析，但目前不能从任意视频可靠还原完整作业。可设置 `prepare_only: true` 只获取并解析，不操作游戏；详细适用范围见[视频解析](../video-strategies.md)。

允许本地试打时，会先核对五名角色，再按失败记录有限重试或换队；有依据的替补属于本地试验，不冒充来源推荐。战前可用游戏的“自动装备”调整特别装备，它可能从其他角色取现有装备，不进行强化或分解。五星升级和女神秘石兑换是两个独立的消费开关，默认都关闭；不购买体力、重置次数、升六星或投入专武资源。

以战后同属性 NEXT 前进确认过关。次数用尽、体力不足、无可用队伍、身份/专武不明或未知页面会在运行记录中给出原因；无 NEXT 不直接等于全部通关。记录位于 `cache/daily/runs/`；地图和养成页面的游戏知识见[深域](../game-knowledge/abyss.md)。

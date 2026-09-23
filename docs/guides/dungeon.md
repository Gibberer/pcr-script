# 地下城首通

按需任务 `dungeon_first_clear`；GUI 从“按需专项”选择，命令行为：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py dungeon_first_clear
```

当前实机验证区域为“四彩的灵峰”（极难 7）、雷电 960×540。任务读取区域完成标记、当前层数、首领阶段、剩余 HP 与可用角色；已通关区域会跳过。前四层和第五层首领需要完整路线，不能只找到一支队伍便断言可以首通。

## 方案与来源

可将本任务优先攻略链接写在 `Dungeon.source_urls`；缺少本地方案时会搜索并解析已支持的视频布局。当前有限自动路线只接受同一来源、前四层齐全、春夏秋冬各一队且无成员冲突的“四彩灵峰”方案；复杂多刀路线和最优替换尚不能自动规划。设置 `Dungeon.prepare_only: true` 可只解析来源，不操作游戏。解析范围见[视频解析](../video-strategies.md)。

本地方案保存在忽略的 `cache/game/strategies/dungeon_teams.yml`，不随仓库分发。YAML 包含 `version: 1`、`area` 和 `parties`；每支队伍需唯一 `id`、楼层 `floor`、第五层阶段 `phase`、`source` 与五名完整衣装的 `members`，并明确相关培养和 SET 要求。默认开战前核对整条首领路线的队伍可用性及跨队占用；`audit_only: true` 只检查，不开战。预检通过不保证伤害足以首通。

`allow_local_trials` 默认关闭。开启后可用当前账号已核验状态进行有限试验，结果标为本地试打，不当作原攻略要求。可选 `auto_equip: true` 调配现有特别装备，可能改变其他角色配装；不购买或强化装备。

## 进度与结果

每战前后读取当前楼层、阶段、HP 和可用角色数，按实际保留伤害接续。战斗菜单撤退与整场区域撤退不同，任务不会为恢复而退出整个区域。进程在战斗中断后，不会盲目重放未确认的一场；先核对游戏实际进度。运行记录在 `cache/daily/runs/`，接续状态在 `cache/daily/dungeon_state/`，多账号共用设备时要设置不同的 `Dungeon.account_key`。

最终只以目标区域卡片“已完成！”判定首通。自动获取完整多队路线及新区域连续首通仍有待验收；游戏楼层和首领机制见[地下城知识](../game-knowledge/dungeons.md)。

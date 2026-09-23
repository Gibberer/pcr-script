# 任务使用指南

GUI 的“每日日常”会按顺序执行预设列表；完成首次设置后就可以点击“开始今日日常”。“按需专项”每次只处理一个目标。两者使用同一份 Python 任务实现与运行记录。首次设置见 [GUI 指南](desktop.md)。

## 一、日常任务

新工程从 `runtime_defaults.yml` 加载一组现成的日常任务，无需逐项添加。需要自定义时，选中任务修改参数、启用状态或顺序，也可以点“＋ 添加任务”扩充列表。相同任务可以出现多次，例如扫荡前后分别领取首页任务奖励。

| 任务 | 注册名 | 参数与注意点 |
|---|---|---|
| 免费十连 | `free_gacha` | 是否抽取全部累积次数；完整日常按活动情报筛选 |
| 普通扭蛋 | `normal_gacha` | 需要有免费次数 |
| 日程表 | `schedule` | 使用游戏中已保存的日程安排 |
| 竞技场 / 公主竞技场 | `arena` / `princess_arena` | 使用已保存队伍，各挑战一次 |
| 圣迹 / 神殿调查 | `research` | 使用可用次数和体力 |
| 冒险日常 | `adventure_daily` | 探险归来、再次出发及地图事件 |
| 首页任务领奖 | `get_quest_reward` | 依次检查每日、普通、称号三个标签，领取已完成任务奖励，可能包含体力 |
| 礼物箱 | `get_gift` | 可选择暂不领取体力；满仓处理见 [礼物说明](../game-knowledge/gifts.md) |
| 剧情活动日常 | `campaign_clean` | 困难扫荡、普通扫荡开关；剧情、领奖、兑换放在日常选项；[详细说明](story-event.md) |
| 活动首通兼容入口 | `clear_campaign_first_time` | 首通仍取决于配置开关，默认关闭；不是额外独立实现 |
| 复刻活动 | `revival_event_once` | 活动情报筛选、完成回执跳过；[详细说明](../game-knowledge/revival-events.md) |
| 快捷扫荡 | `quick_clean` | 游戏中预设 1～7；仅困难掉落活动时可能切预设 3，先核对游戏内预设 |
| 露娜塔回廊扫荡 | `luna_tower_clean` | 需活动开放且满足扫荡条件，不是自动登塔 |
| 商店购买 | `shop_buy` | JSON 购买规则，会消耗对应货币；`{"1":[-1]}` 为通常商店“全部”分类全选。当前支持通常/限定全选及各商店首屏 1～4 号商品；刷新与后续页商品暂不支持，详见[商店界面记录](../game-knowledge/shop-quests.md) |

默认执行顺序见 [runtime_defaults.yml](../../runtime_defaults.yml)，更多参数写法见 [daily.example.yml](examples/daily.example.yml)。GUI 中主动选择“新建配置”会得到空白列表，供自行编排；默认列表不包含地下城、深域或角色培养。需要首页的任务由统一调度返回首页，不必穿插 `tohomepage`；不能识别的弹窗保留现场。

命令行和 GUI 默认先查找 `daily_config.yml`，没有时使用根目录 `runtime_defaults.yml`；也可指定自己的 YAML。完整日常运行 `daily_task.py --config <配置文件>`，脚本按所选文件的 `Task` 列表执行。GUI 编辑第一个任务组，保留已有账号与其他组，但不提供账号登录或多组切换。

## 二、单项与专项任务

在“按需专项”选择任务，阅读起始页面和消费范围，调整“本次运行选项”，点击“执行本次专项”。这些选项不会写回日常配置。日常列表中的项目也可用右侧“单独执行选中项”执行一次。

命令行通用形式：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py <注册名> --config daily_config.yml
```

有位置参数时使用 `--args` JSON 数组；任务配置段仍来自 YAML。

| 专项 | 注册名 | 用法与核心逻辑 |
|---|---|---|
| 地下城首通 | `dungeon_first_clear` | `Dungeon` 配置；读层数/阶段 → 获取来源或本地路线 → 检查跨队占用与培养 → 有限挑战并核验进展；[详细指南](dungeon.md) |
| 深域推进 | `abyss_push` | `Abyss` 配置；定位各属性 NEXT → 获取适用来源 → 核验账号 → 按结果与历史有限重试；以 NEXT 前进确认通关；[详细指南](abyss.md) |
| 全角色强化 | `upgrade_all_characters` | 游戏一键强化分批提升等级、技能和普通装备，消耗现有材料；[范围说明](character-upgrade.md) |
| 好感度与角色剧情 | `max_character_bonds` | 使用持有礼物提升好感度，处理已开放剧情；[详细说明](character-bond.md) |
| 驾车游 | `caravan` | 持有骰子达标前单骰、满足条件后快速通关；[详细说明](../game-knowledge/caravan.md) |
| 阅读剧情 | `clear_story` | 处理剧情页可读内容 |
| 普通冒险 | `common_adventure` | 先进入目标地图，依靠角色模板定位并循环战斗，需要主动停止 |
| 返回首页 | `tohomepage` | 手动导航工具；普通日常不需重复配置 |

### 地下城与深域的来源处理

优先链接分别填写 `Dungeon.source_urls`、`Abyss.source_urls`，不跨任务共享。没有完整方案时自动搜索、获取视频、建立公共头像索引并解析已支持的布局。逐字段保存来源、截图与时间点；未知专武状态不变成“未开启”。开战前仍核对本地角色，不用账号当前培养补写来源缺失要求。

打开 `prepare_only` 可只获取并解析来源，深域需指定 `sources.stage` 和 `sources.element`。当前视频解析、多刀地下城规划和全局培养核验仍有待办，不能保证生成每个关卡的完整作业；见[解析范围](../video-strategies.md)。无法确认时可查看报告与证据，再决定是否调整来源。

`allow_local_trials` 明确允许按当前账号进行试验，默认关闭；试验结果不代表复现源作业。深域五星升级与秘石兑换另有独立开关，默认关闭；不自动购买体力、重置次数或投入专武资源。

### 如何判断结果

在运行记录查看具体任务结果、剩余原因与截图。`partial` 表示只完成一部分，`blocked` 表示前置条件未确认；退出或胜利动画不等于全部目标完成。停止/暂停需等状态确认，未确认时不并行启动另一进程操作同一模拟器。排查见[运行诊断](../run-diagnostics.md)。

# 入口分类

| 路径 | 用途 | 可以放入定时任务 |
|---|---|---|
| 根目录 `daily_task.py` | 现有完整日常，读取 `daily_config.yml` | 是 |
| `scripts/daily/all.bat` | 完整日常定时入口，自动设置工作目录和本地 Python，无暂停 | 是 |
| `scripts/daily/task.py <任务名>` | 从统一注册表按需执行一个 Task，读取同一份配置 | 按需启用 |
| `scripts/daily/story_event.py` | 单独执行固化的剧情活动日常 | 是 |
| `scripts/daily/story_event.bat` | 单独活动的 Windows 定时入口，无暂停 | 是 |
| `scripts/daily/revival_event.py` / `.bat` | 情报识别复刻，每期首通及领奖一次，完成后跳过 | 是 |
| `scripts/daily/gifts.py` | 单独领取礼物，自动恢复特别装备满仓 | 是 |
| `scripts/daily/caravan.py` / `.bat` | 按需清空驾车游持有骰子；独立任务，不加入完整每日列表 | 按需启用 |
| `scripts/agent/game.py` | 截图、OCR、后台点击/输入、配队审查 | 否 |
| `scripts/agent/update_avatars.py` | 维护日服头像索引 | 否，按需更新 |
| `scripts/_game.py` | 共用启动配置，无任务动作 | 不是运行入口 |

共享界面能力在 `pcrscript/game_ui/`；活动流程在 `pcrscript/tasks/`；真实作业为本地运行数据，存 `cache/game/strategies/`，不提交；Agent 知识在 `docs/game-knowledge/`。Agent 工具仅用于分析，正式入口不得依赖先运行它们。当前头像与队伍方案的正式自动获取链路仍待实现，不能将已有缓存下的成功当作端到端完成。

所有正式任务统一位于 `pcrscript/tasks/`，通过 `Robot.run_task` 调度；专用入口仅解析参数，不另建 Runner。原来的任务名、配置列表和公开导入保持兼容。结构、配置优先级、报告类型与按运行归档见 [任务架构](../docs/task-architecture.md)。

```powershell
# 日常；也可继续运行原来的 daily_task.py
./.venv/Scripts/python.exe -X utf8 scripts/daily/story_event.py
# Agent 观察与核验
./.venv/Scripts/python.exe -X utf8 scripts/agent/game.py
./.venv/Scripts/python.exe -X utf8 scripts/agent/game.py --audit
./.venv/Scripts/python.exe -X utf8 scripts/agent/update_avatars.py --all
```

日常结果写入 `cache/daily/`，Agent 观察写入 `cache/agent/`，共用头像索引写入 `cache/game/avatars/`。早期开发截图仍在 `cache/story_event/`，仅作历史证据。

## 礼物满仓恢复

`scripts/daily/gifts.py` 为独立礼物日常入口，完整日常仍使用配置中的 `get_gift`。它在持有上限阻塞后使用游戏已保存的自动分解规则腾出特别装备空间，再继续分批领取。配置见 `_daily_config.yml` 的 `Gift`；默认排除体力、目标空位 750，不修改游戏分解设置。实测导航与约束见 [礼物知识](../docs/game-knowledge/gifts.md)。

每日入口自动保存运行日志与异常现场；中途暂停/恢复、证据格式及排查流程见 [运行诊断](../docs/run-diagnostics.md)。控制入口为 scripts/agent/run_control.py。

## 驾车游（独立按需任务）

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/caravan.py
# 同一个 Task 的通用入口
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py caravan
# 或 scripts/daily/caravan.bat
```

模拟器与游戏须已打开；支持从首页/冒险菜单/驾车游及已识别的中断弹窗继续。任务名 `caravan` 已注册，但不会自动加入 `daily_config.yml` 或完整每日列表。普通投骰强制关闭“同时掷3个”，目标15回合内到检查点；解锁后优先区间跳过，不足15骰子继续单骰。默认1800秒、200批，可用 `--timeout`、`--max-rolls` 调整。数字未知、消费不符或未知弹窗会停止留证；不购买骰子/体力，不花费里程，不重置进度。规则及实测范围见 [驾车游](../docs/game-knowledge/caravan.md)。

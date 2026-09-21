# 项目目录说明

目录职责与任务文件索引集中维护在 `docs/`，代码目录不新增 README。任务执行与基类设计见 [任务组织与执行](task-architecture.md)。

| 路径 | 职责 |
|---|---|
| `daily_task.py` | 完整每日任务兼容入口 |
| `pcrscript/tasks/` | 统一任务实现、基类、注册表及任务辅助逻辑 |
| `pcrscript/game_ui/` | 可共享的观察、识别与操作能力 |
| `scripts/daily/` | 正式自动化命令入口，可供定时任务调用 |
| `scripts/agent/` | 分析、探查、审查与校准工具 |
| `test/` | 离线回归测试与最小测试样本 |
| `docs/` | 项目结构、运行方式与设计说明 |
| `docs/game-knowledge/` | 游戏规则、界面知识与待验证场景 |
| `cache/daily/` | 日常运行结果与证据，本地数据不提交 |
| `cache/agent/` | Agent 分析证据，本地数据不提交 |
| `cache/game/` | 共享识别数据及实际队伍方案，本地数据不提交 |

## 任务文件索引

`task_*.py` 存放具体 Task 实现。`base.py`、`image.py` 是基类，`registry.py` 是注册表；`_actions.py`、`event_*.py`、`revival_map.py`、`revival_state.py` 是辅助逻辑，不是独立任务入口。

### 可通过配置或通用命令运行的任务

| 实现文件 | 注册任务名 |
|---|---|
| [task_adventure.py](../pcrscript/tasks/task_adventure.py) | `adventure_daily`、`common_adventure`、`quick_clean` |
| [task_caravan.py](../pcrscript/tasks/task_caravan.py) | `caravan` |
| [task_gacha.py](../pcrscript/tasks/task_gacha.py) | `free_gacha`、`normal_gacha` |
| [task_gifts.py](../pcrscript/tasks/task_gifts.py) | `get_gift` |
| [task_home.py](../pcrscript/tasks/task_home.py) | `tohomepage` |
| [task_revival_event.py](../pcrscript/tasks/task_revival_event.py) | `revival_event_once` |
| [task_routines.py](../pcrscript/tasks/task_routines.py) | `arena`、`princess_arena`、`research`、`schedule` |
| [task_shop.py](../pcrscript/tasks/task_shop.py) | `shop_buy` |
| [task_story.py](../pcrscript/tasks/task_story.py) | `clear_story`、`get_quest_reward` |
| [task_story_event.py](../pcrscript/tasks/task_story_event.py) | `campaign_clean`、`campaign_reward_exchange`、`clear_campaign_first_time` |
| [task_tower.py](../pcrscript/tasks/task_tower.py) | `luna_tower_clean`、`luna_tower_climbing` |

`task_combat.py` 包含可复用的 `TeamFormation`、`TeamFormationEx`、`Combat` 子任务，供其他任务通过 Python 调用，未注册为独立命令，不能直接填入配置任务列表。

通用命令：`./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py <注册任务名>`（在项目根目录运行）。驾车游 `caravan` 仍仅按需启用。

新增具体任务使用 `task_<功能>.py`，需要独立调度时使用 `@register(...)` 并在 `__init__.py` 导入，同时更新本表。对外优先从 `pcrscript.tasks` 导入任务类；文件改名不改变类名、注册名和脚本命令。

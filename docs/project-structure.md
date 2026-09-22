# 项目目录说明

目录职责与任务文件索引集中维护在 `docs/`，代码目录不新增 README。任务执行与基类设计见 [任务组织与执行](task-architecture.md)。

| 路径 | 职责 |
|---|---|
| `daily_task.py` | 完整每日任务兼容入口 |
| `desktop/PcrDesktop/` | C# / WPF 图形控制台源码，发布为独立 EXE |
| `pcrscript/runtime.py` | GUI 与兼容命令入口共用的配置、每日流程及任务执行逻辑 |
| `pcrscript/runtime_defaults.yml` | 核心运行目录自带的默认选项，无账号和默认任务 |
| `pcrscript/desktop.py` | GUI 使用的版本化 JSON 配置、控制和运行入口 |
| `.github/workflows/desktop.yml` | Windows GUI 自动构建、离线测试与 EXE 产物上传 |
| `pcrscript/tasks/` | 统一任务实现、基类、注册表及任务辅助逻辑 |
| `pcrscript/game_ui/` | 可共享的观察、识别与操作能力；`dungeon.py` 读取进度，`character_equipment.py` 只读核验未开放专武 |
| `scripts/daily/` | 正式自动化命令入口，可供定时任务调用 |
| `scripts/legacy/multi_account.py` | 旧版多账号入口，从根目录运行；不属于 GUI 核心下载 |
| `docs/examples/daily.example.yml` | 可复制到根目录的日常示例配置 |
| `requirements.txt` | 唯一 Python 依赖清单，包含 OCR |
| `scripts/agent/` | 分析、探查、审查与校准工具 |
| `test/` | 离线回归测试与最小测试样本 |
| `docs/` | 项目结构、运行方式与设计说明 |
| `docs/game-knowledge/` | 游戏规则、界面知识与待验证场景 |
| `cache/daily/` | 日常运行结果与证据，本地数据不提交 |
| `cache/agent/` | Agent 分析证据，本地数据不提交 |
| `cache/game/` | 共享识别数据及实际队伍方案，本地数据不提交 |

GUI 下载可选择仅核心运行目录（`pcrscript/`、`images/` 和统一 requirements 清单）或完整仓库。精简运行目录无需 `scripts/` 和根目录 Python 入口。

GUI 的使用、构建和发布方式见 [Windows 图形控制台](desktop.md)。

## 任务文件索引

`task_*.py` 存放具体 Task 实现。`base.py`、`image.py` 是基类，`registry.py` 是注册表；`_actions.py`、`event_*.py`、`revival_map.py`、`revival_state.py` 是辅助逻辑，不是独立任务入口。

### 可通过配置或通用命令运行的任务

| 实现文件 | 注册任务名 |
|---|---|
| [task_adventure.py](../pcrscript/tasks/task_adventure.py) | `adventure_daily`、`common_adventure`、`quick_clean` |
| [task_character_upgrade.py](../pcrscript/tasks/task_character_upgrade.py) | `upgrade_all_characters` |
| [task_dungeon.py](../pcrscript/tasks/task_dungeon.py) | `dungeon_first_clear` |
| [task_caravan.py](../pcrscript/tasks/task_caravan.py) | `caravan` |
| [task_gacha.py](../pcrscript/tasks/task_gacha.py) | `free_gacha`、`normal_gacha` |
| [task_gifts.py](../pcrscript/tasks/task_gifts.py) | `get_gift` |
| [task_home.py](../pcrscript/tasks/task_home.py) | `tohomepage` |
| [task_revival_event.py](../pcrscript/tasks/task_revival_event.py) | `revival_event_once` |
| [task_routines.py](../pcrscript/tasks/task_routines.py) | `arena`、`princess_arena`、`research`、`schedule` |
| [task_shop.py](../pcrscript/tasks/task_shop.py) | `shop_buy` |
| [task_story.py](../pcrscript/tasks/task_story.py) | `clear_story`、`get_quest_reward` |
| [task_story_event.py](../pcrscript/tasks/task_story_event.py) | `campaign_clean`、`clear_campaign_first_time` |
| [task_tower.py](../pcrscript/tasks/task_tower.py) | `luna_tower_clean`、`luna_tower_climbing` |

`task_combat.py` 包含可复用的 `TeamFormation`、`TeamFormationEx`、`Combat` 子任务，供其他任务通过 Python 调用，未注册为独立命令，不能直接填入配置任务列表。

通用命令：`./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py <注册任务名>`（在项目根目录运行）。驾车游 `caravan` 仍仅按需启用。

新增具体任务使用 `task_<功能>.py`，需要独立调度时使用 `@register(...)` 并在 `__init__.py` 导入，同时更新本表。对外优先从 `pcrscript.tasks` 导入任务类；文件改名不改变类名、注册名和脚本命令。

地下城识别位于 `game_ui/dungeon.py`，方案校验、跨队冲突与编队布局位于 `tasks/dungeon_party.py`，候选头像盘点位于 `game_ui/roster.py`，均非独立任务。运行与本地方案格式见 [地下城首通](dungeon.md)。

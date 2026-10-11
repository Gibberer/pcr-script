# 项目目录说明

目录职责与任务文件索引集中维护在 `docs/`，代码目录不新增 README。任务执行与基类设计见 [任务组织与执行](task-architecture.md)。

| 路径 | 职责 |
|---|---|
| `daily_task.py` | 完整每日任务兼容入口 |
| `desktop/PcrDesktop/` | C# / WPF 图形控制台源码，发布为独立 EXE |
| `pcrscript/runtime.py` | GUI 与兼容命令入口共用的配置、每日流程及任务执行逻辑 |
| `runtime_defaults.yml` | GUI 与命令行共用的默认配置；无账号，预置日常任务列表 |
| `pcrscript/desktop.py` | GUI 使用的版本化 JSON 配置、控制和运行入口 |
| `.github/workflows/desktop.yml` | Windows GUI 构建、离线测试与产物上传；已合并版本标签创建 Release |
| `.github/workflows/python.yml` | 普通 Python 代码、依赖与默认配置变更的离线回归 |
| `pcrscript/tasks/` | 统一任务实现、基类、注册表及任务辅助逻辑 |
| `pcrscript/game_ui/` | 可共享的观察、识别与操作能力；`dungeon.py` 读取进度，`character_equipment.py` 只读核验专武开放与已支持的强化数值，`ordinary_equipment.py` 读取普通装备槽的开放及穿戴状态 |
| `scripts/daily/` | 正式自动化命令入口，可供定时任务调用 |
| `scripts/legacy/multi_account.py` | 旧版多账号入口，从根目录运行；不属于 GUI 核心下载 |
| `docs/guides/examples/daily.example.yml` | 可复制到根目录的日常示例配置 |
| `requirements.txt` | 唯一 Python 依赖清单，包含 OCR |
| `scripts/agent/` | 分析、探查、审查与校准工具 |
| `test/` | 离线回归测试与最小测试样本 |
| `docs/` | 项目结构、运行方式与设计说明 |
| `docs/game-knowledge/` | 游戏规则、界面知识与待验证场景 |
| `cache/daily/` | 日常运行结果与证据，本地数据不提交 |
| `cache/agent/` | Agent 分析证据，本地数据不提交 |
| `cache/game/` | 共享识别数据及实际队伍方案，本地数据不提交 |

GUI 下载可选择仅核心运行目录（`pcrscript/`、`images/`、根目录 `requirements.txt` 与 `runtime_defaults.yml`）或完整仓库。精简运行目录无需 `scripts/` 和根目录 Python 入口。

GUI 使用见 [图文指南](guides/desktop.md)，日常与专项见 [任务指南](guides/tasks.md)，构建与发布见 [发布指南](releases.md)。`docs/guides/images/gui-*.png` 是离线示例界面，无账号数据。

GUI 的 `MainWindow.DailyEditor.cs` 管理选中项编辑、顺序和未保存状态；`AddTaskWindow` 隔离新增草稿；`TaskParameters.cs` 为日常、专项和添加窗口共用的参数表单与校验。游戏逻辑仍只在 Python 中实现。

GUI 的 `PortableTools.cs` 管理固定版本工具的下载、SHA-256 校验与安全解压；`RuntimeSource.cs` 复用系统 Git 或便携 MinGit 下载与更新源码；`PythonEnvironment.cs` 负责检测/下载 Python、创建 `.venv`、安装检查及本地日志。`pcrscript/desktop.py devices` 通过现有 `simulator.py` 只读枚举连接状态，运行锁占用时拒绝检查。合成 GUI 验证入口不连接游戏；全新环境安装验证见[发布指南](releases.md)。

## 任务文件索引

`task_*.py` 存放具体 Task 实现。`base.py`、`image.py` 是基类，`registry.py` 是注册表；其余不以 `task_` 开头的模块提供配置、页面流程、配队和状态等辅助逻辑，不是独立任务入口。

### 可通过配置或通用命令运行的任务

| 实现文件 | 注册任务名 |
|---|---|
| [task_adventure.py](../pcrscript/tasks/task_adventure.py) | `adventure_daily`、`common_adventure`、`quick_clean` |
| [task_character_upgrade.py](../pcrscript/tasks/task_character_upgrade.py) | `upgrade_all_characters` |
| [task_character_bond.py](../pcrscript/tasks/task_character_bond.py) | `max_character_bonds`（现有礼物与角色剧情） |
| [task_dungeon.py](../pcrscript/tasks/task_dungeon.py) | `dungeon_first_clear` |
| [task_abyss.py](../pcrscript/tasks/task_abyss.py) | `abyss_push`（深域按需推进） |
| [task_abyss_subjugation.py](../pcrscript/tasks/task_abyss_subjugation.py) | `abyss_subjugation`（深渊讨伐战每日首通与扫荡） |
| [task_recollection_first_clear.py](../pcrscript/tasks/task_recollection_first_clear.py) | `recollection_first_clear`（普通及霸首通） |
| [task_recollection.py](../pcrscript/tasks/task_recollection.py) | `recollection`（普通报酬及已通关霸扫荡） |
| [task_caravan.py](../pcrscript/tasks/task_caravan.py) | `caravan` |
| [task_dawn_labyrinth.py](../pcrscript/tasks/task_dawn_labyrinth.py) | `dawn_labyrinth`（仅已通关难度跳过） |
| [task_dawn_labyrinth_first_clear.py](../pcrscript/tasks/task_dawn_labyrinth_first_clear.py) | `dawn_labyrinth_first_clear`（美食殿堂难度 1 的一次探索） |
| [task_team_battle.py](../pcrscript/tasks/task_team_battle.py) | `team_battle` |
| [task_gacha.py](../pcrscript/tasks/task_gacha.py) | `free_gacha`、`normal_gacha` |
| [task_gifts.py](../pcrscript/tasks/task_gifts.py) | `get_gift` |
| [task_home.py](../pcrscript/tasks/task_home.py) | `tohomepage` |
| [task_revival_event.py](../pcrscript/tasks/task_revival_event.py) | `revival_event_once` |
| [task_routines.py](../pcrscript/tasks/task_routines.py) | `arena`、`princess_arena`、`research`、`schedule` |
| [task_shop.py](../pcrscript/tasks/task_shop.py) | `shop_buy` |
| [task_story.py](../pcrscript/tasks/task_story.py) | `clear_story`、`get_quest_reward` |
| [task_story_event.py](../pcrscript/tasks/task_story_event.py) | `campaign_clean`、`clear_campaign_first_time` |
| [task_tower.py](../pcrscript/tasks/task_tower.py) | `luna_tower_clean`（回廊扫荡） |

`task_combat.py` 包含可复用的 `TeamFormation`、`TeamFormationEx`、`Combat` 子任务，供其他任务通过 Python 调用，未注册为独立命令，不能直接填入配置任务列表。

命令与配置见[命令行指南](guides/command-line.md)，是否加入日常列表见[任务指南](guides/tasks.md)。

新增具体任务使用 `task_<功能>.py`，需要独立调度时使用 `@register(...)` 并在 `__init__.py` 导入，同时更新本表。对外优先从 `pcrscript.tasks` 导入任务类；文件改名不改变类名、注册名和脚本命令。

## 共享模块索引

下列模块供任务组合调用，不注册为独立命令。这里维护文件位置；行为约束和验收条件在各专题维护。

| 能力 | 模块 | 主文档 |
|---|---|---|
| 配置、记录与运行控制 | `tasks/options.py`、`run_session.py` | [任务架构](task-architecture.md)、[运行诊断](run-diagnostics.md) |
| 编队、培养差距及特别装备 | `tasks/strategy_formation.py`、`party_preparation.py`；`game_ui/character_search.py`、`character_equipment.py`、`ordinary_equipment.py`、`character_stars.py`、`special_equipment.py`；`character_data.py` | [公共准备流程](party-preparation.md) |
| 公共攻略与视频解析 | `tasks/strategy_sources.py`、`strategy_inputs.py`、`strategy_video.py`、`strategy_document.py`、`strategy_tables.py`、`strategy_party_pool.py`、`strategy_trial.py`；`extras/guide_media.py`；`game_ui/avatar_assets.py`、`guide_vision.py` | [视频解析](video-strategies.md) |
| 深域尝试与替补 | `tasks/abyss_history.py`、`abyss_retry.py`、`party_variants.py`；`game_ui/abyss.py` | [深域推进](guides/abyss.md) |
| 深渊来源与本期编队 | `tasks/subjugation_guides.py`、`subjugation_party.py`；`game_ui/abyss_subjugation.py`；`news.py` 的 `abyss_schedule` | [深渊讨伐战](guides/abyss-subjugation.md) |
| 追忆导航、来源及恢复 | `tasks/recollection_flow.py`、`recollection_strategy.py`、`recollection_retry.py`；`game_ui/recollection.py` | [追忆战场](guides/recollection.md) |
| 可选职能精通准备 | `tasks/role_mastery_preparation.py`、`game_ui/role_mastery.py` | [精通配置与消费恢复](guides/recollection.md#可选职能精通准备) |
| 地下城方案与编队 | `tasks/dungeon_party.py`、`game_ui/dungeon.py`、`game_ui/roster.py` | [地下城首通](guides/dungeon.md) |
| 迷宫页面与首通编队 | `game_ui/dawn_labyrinth.py`、`tasks/dawn_labyrinth_party.py` | [黎明界迷宫](guides/dawn-labyrinth.md) |

`tasks/abyss_party.py` 只保留 `StrategyFormation` 的旧导入别名。公共能力在共享模块中维护，玩法任务负责自己的导航、目标、预算和结果核验。

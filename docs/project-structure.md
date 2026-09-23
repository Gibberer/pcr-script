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
| `pcrscript/game_ui/` | 可共享的观察、识别与操作能力；`dungeon.py` 读取进度，`character_equipment.py` 只读核验未开放专武 |
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

## 任务文件索引

`task_*.py` 存放具体 Task 实现。`base.py`、`image.py` 是基类，`registry.py` 是注册表；`_actions.py`、`event_*.py`、`revival_map.py`、`revival_state.py` 是辅助逻辑，不是独立任务入口。

### 可通过配置或通用命令运行的任务

| 实现文件 | 注册任务名 |
|---|---|
| [task_adventure.py](../pcrscript/tasks/task_adventure.py) | `adventure_daily`、`common_adventure`、`quick_clean` |
| [task_character_upgrade.py](../pcrscript/tasks/task_character_upgrade.py) | `upgrade_all_characters` |
| [task_character_bond.py](../pcrscript/tasks/task_character_bond.py) | `max_character_bonds`（现有礼物与角色剧情） |
| [task_dungeon.py](../pcrscript/tasks/task_dungeon.py) | `dungeon_first_clear` |
| [task_abyss.py](../pcrscript/tasks/task_abyss.py) | `abyss_push`（深域按需推进） |
| [task_caravan.py](../pcrscript/tasks/task_caravan.py) | `caravan` |
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

通用命令：`./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py <注册任务名>`（在项目根目录运行）。驾车游 `caravan` 仍仅按需启用。

新增具体任务使用 `task_<功能>.py`，需要独立调度时使用 `@register(...)` 并在 `__init__.py` 导入，同时更新本表。对外优先从 `pcrscript.tasks` 导入任务类；文件改名不改变类名、注册名和脚本命令。

地下城识别位于 `game_ui/dungeon.py`，方案校验、跨队冲突与编队布局位于 `tasks/dungeon_party.py`，候选头像盘点位于 `game_ui/roster.py`，均非独立任务。运行与本地方案格式见 [地下城首通](guides/dungeon.md)。

`tasks/strategy_sources.py` 为内部共享的匿名来源搜索/身份核验/缓存能力，不注册为独立任务。深域与地下城首通按各自任务配置调用搜索，攻略链接分别配置于 `Abyss.source_urls`、`Dungeon.source_urls`。候选来源不是战斗方案。`tasks/abyss_party.py` 为本地试打编队检查，`game_ui/abyss.py` 为深域地图识别，均非独立任务。使用方式见 [深域推进](guides/abyss.md)。

深域辅助模块：`pcrscript/tasks/abyss_history.py` 保存按账号/关卡隔离的尝试历史；`abyss_retry.py` 根据战斗证据决定重试价值；`party_variants.py` 按数据库技能描述生成本地替代组合，均不独立注册任务。


深域与来源共享辅助模块：`tasks/strategy_inputs.py` 统一用户链接及UP评论引用；`tasks/strategy_tables.py` 解析简单通用头像表；两者均非独立任务。`game_ui/character_stars.py` 为默认关闭的五星培养/兑换与回执能力，供深域任务组合使用，非独立注册入口。

视频解析辅助模块：`tasks/strategy_video.py` 负责来源到字段证据的获取/关联，`tasks/strategy_document.py` 保留未知与冲突并适配正式任务，`tasks/strategy_party_pool.py` 整理活动首领的自动来源、有限试打和职责替补候选，`tasks/strategy_trial.py` 以账号实时观察核验试打编队；`extras/guide_media.py` 下载/校验视频，`game_ui/avatar_assets.py` 自动准备公共头像与国服身份，`game_ui/guide_vision.py` 提供视频布局识别。均不独立注册任务，由深域、地下城首通、剧情活动及复刻活动复用；深域和地下城支持 `prepare_only`，详见 [视频解析与复核](video-strategies.md)。

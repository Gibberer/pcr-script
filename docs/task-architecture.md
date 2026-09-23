# 任务组织与执行

2026-09-21 按用户反馈将 `pcrscript/tasks.py` 拆为 `pcrscript/tasks/`，把原 `pcrscript/daily/` 实现并入同一任务包。没有第二套 Runner 框架；任务按功能组织，与是否每日执行无关。

- `base.py`：与识别方式无关的 BaseTask、TimeLimitTask、活动数据类型、公共配置与接口类型。
- `image.py`：ImageTask，仅供图片匹配任务使用的动作序列、模板匹配、设计坐标换算与进度能力。
- `registry.py`：唯一任务注册表。`__init__.py` 负责注册加载和兼容导出。
- `task_home.py`、`task_gacha.py`、`task_adventure.py`、`task_shop.py`、`task_story.py`、`task_routines.py`、`task_combat.py`、`task_tower.py`：从原文件拆出的任务与动作实现。2026-09-23 删除了不可用的露娜塔登塔旧实现；`task_tower.py` 仅保留回廊扫荡。
- `task_story_event.py`、`task_revival_event.py`、`task_gifts.py`、`task_caravan.py`：直接实现并注册 Task；活动战斗、配队、扫荡、作业校验及复刻地图等辅助模块同属 tasks 包。
- `game_ui/` 仍仅放可共享的识别/操作能力；`scripts/agent/` 仅分析；`scripts/daily/` 仅命令适配与原有兼容入口。

原来的 `from pcrscript.tasks import BaseTask, CampaignClean, ...`、任务列表位置参数保持兼容；2026-09-21 收尾按用户要求移除独立 `campaign_reward_exchange`，活动日常自动处理领奖/兑换，目前20个注册任务。原 `pcrscript.daily.*` 是此次被移除的内部路径，工程内引用和测试均已迁移。

具体任务文件统一以 `task_` 开头，基础设施和辅助模块不加此前缀；完整注册名与文件对应关系见 [任务索引](project-structure.md)。`task_combat.py` 是未独立注册的可复用子任务，索引中单独说明。原模块路径随文件名调整，对外类导出、注册名和脚本命令不变。

## 按能力拆分基类

2026-09-21 按用户反馈，`BaseTask` 只保留 Robot/Driver 上下文、配置、只读预检和运行契约。OCR 任务组合已有 `EventUI`，不再继承未使用的图片动作接口，也不新增无实际共性的 OCR 基类。

原图片任务改为继承 `ImageTask`。限时规则不依赖识别方式：图片限时任务使用 `class FreeGacha(ImageTask, TimeLimitTask)`；OCR 活动任务使用 `class CampaignClean(TimeLimitTask)`。两者仍由同一注册表、活动筛选和调度器执行。

动作只依赖 `ActionContext` 协议中的设计宽高，不依赖具体任务类；`bindTask()` 使用 `Self` 保留具体动作类型。进度总数兼容原编队任务使用的无限标记。

扩展迁移：自行编写且调用 `action_squential()`、`template_match()`、坐标或进度方法的旧 `BaseTask` 子类，需要改为继承 `ImageTask`。内置任务已迁移；公开任务导入路径与注册名保持不变，但 `BaseTask` 本身不再提供图片能力。

## 一条执行路径

完整日常调用 `Robot.configure(config)` 和 `Robot.work(task_list)`；单项入口调用同一个 `Robot.run_task(name, *args, **kwargs)`。新 Task 通过 `task_options()` 获取统一配置，兼容旧 Robot 的 options 属性。任务实例不修改调用者配置。

单项命令先调用 Task 的只读 `prepare()`。复刻在没有有效活动或显式账号完成回执时，在枚举模拟器之前返回。日常已有 Robot 的复刻 Task 也复用同一预检规则。

```powershell
# 按需执行，完全不修改每日列表
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py caravan
# 原有专用命令继续可用
./.venv/Scripts/python.exe -X utf8 scripts/daily/caravan.py --max-rolls 200
```

`Caravan`、`Gift`、`StoryEvent`、`RevivalEvent` 配置段由同一配置加载链传入。命令参数仅覆盖明确传入的字段；不覆盖配置文件里的其余值。配置段存在不会自动加入 `Task` 列表，驾车游仍仅按需运行。

## 结果与错误

调度器保存每个任务返回的报告并向调用方返回。`Robot.task_results` / `work()` 返回执行记录；`events.jsonl` 写入 `task.result`。旧任务没有资源核验报告时只标 `finished`，不能冒充已核验的 `complete`。

有 RunSession 时，每次调度分配 `cache/daily/runs/<run>/tasks/<序号>-<任务名>/`。其中 `result.json` 是统一执行结果，新任务的 report.json、截图与消费证据也写在该目录；同一轮重复执行同名任务不会覆盖。任务配置里的固定 output 只用于无 RunSession 的直接调用/分析，生产调度优先按运行归档。

独立任务异常向上抛出；每日列表保持记录错误后继续下一项。取消旧的 NetError 整任务递归重试：已经发生消费时不能自动重放整个任务。业务内部已有明确余额核验的有限恢复继续保留。旧任务自身无界等待的全面治理仍是独立待办。

## 验证

已离线验证旧注册名/公开导入、每日与独立命令同一调度、配置与位置参数、部分活动步骤、结果归档和不重复执行异常任务。关键入口、任务基类、四项新任务及活动识别/配队/战斗接口已补类型；动态 YAML 扩展字段与各任务异构报告仍使用字典。尚未安装静态类型检查器，不能宣称全项目静态类型检查通过。

真实零骰子验证：`cache/daily/runs/20260921-185618-28520-d52e74/`，统一入口 `task.py caravan` 返回0、complete、spent=0、remaining_dice=0，结果位于 `tasks/001-caravan/result.json`。没有重跑完整每日或消耗任务；该验证不替代带骰子连续清空验收。

收尾离线验收：基类拆分后全套124项测试通过（其中8项任务整合集成测试、6项基类拆分测试）；Python编译检查及 git diff --check 通过。

基类拆分另有6项离线回归，覆盖 OCR 无图片能力依赖、原图片任务继承、动作绑定与坐标换算、进度、Robot 旧动作入口及两类限时任务筛选。本次拆分不操作模拟器；上述零骰子实测发生在拆分之前，拆分后的真实运行留待下次正常任务执行。

2026-09-21：首页要求通过注册参数 `requires_home=True` 声明，由 `Robot.run_task()` 执行前置导航（60秒超时，失败不开始任务）。旧列表无参数 `tohomepage` 分隔项自动省略，带自定义参数的手动项保留。OCR 自有导航和当前地图任务不强制回首页。GUI 任务能力说明与配置编辑见 `docs/desktop.md`。

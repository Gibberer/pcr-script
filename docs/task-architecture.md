# 任务组织与执行

GUI、每日命令和单项命令共用 `pcrscript/tasks/` 中的 Task 注册表与 `Robot.run_task()`。任务按功能归档，与是否加入每日列表无关；注册名和实现文件见[项目结构](project-structure.md)。`pcrscript/game_ui/` 提供可共享的观察、识别与操作能力，`scripts/daily/` 只提供命令入口，`scripts/agent/` 用于分析和校准，不是正式任务的运行前置步骤。

## 任务能力

- `BaseTask` 定义上下文、配置、只读 `prepare()` 与执行契约，并用 `report_progress(label, current=None, total=None)` 上报业务进度，不携带图片匹配接口。步骤总数未知时只传说明，GUI 显示活动中的进度条；有明确上限时同时传当前数与总数。
- `ImageTask` 提供旧图片任务需要的模板匹配、动作绑定、设计坐标换算和动作序列进度；OCR 任务组合 `game_ui` 能力。
- `TimeLimitTask` 独立提供活动时间筛选，可与图片任务或 OCR 任务组合。
- `registry.py` 是唯一注册表；具体任务使用 `task_<功能>.py`，辅助模块不以 `task_` 开头。`task_combat.py` 中的编队与战斗子任务不单独注册。

旧图片任务若使用 `action_squential()`、`template_match()` 或设计坐标接口，应继承 `ImageTask`。动作通过 `ActionContext` 读取设计宽高，实际点击/滑动按最新截图尺寸换算。公开任务类从 `pcrscript.tasks` 导入。

## 配置与调用

完整日常从 YAML 的 `Task` 列表依次调用 `Robot.work()`；GUI 批量运行先将启用项写入同一列表。单项入口调用 `Robot.run_task(name, *args, **kwargs)`，使用选定配置段但不修改每日列表。

```powershell
./.venv/Scripts/python.exe -X utf8 daily_task.py --config daily_config.yml
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py caravan --config daily_config.yml
```

任务需要首页时由注册参数 `requires_home=True` 声明，调度器在运行前导航；有自身导航的 OCR 任务和当前地图任务保持原起点。旧列表中无参数的 `tohomepage` 分隔项会跳过，带自定义参数的手动请求仍执行。活动任务先运行只读 `prepare()`，没有有效目标时可在连接设备前结束。

## 结果与错误

每次调度将执行记录写入 `cache/daily/runs/<run>/tasks/<序号>-<任务名>/result.json`，任务报告与必要截图在同一目录；重复运行同名任务不会覆盖本轮其他任务。`events.jsonl` 记录 `task.result`，运行控制和异常证据见[运行诊断](run-diagnostics.md)。没有业务后置核验的旧任务只标记 `finished`，不能当作资源已确认的 `complete`。

单项任务在运行记录中显示 0/1 到 1/1 的任务级进度；日常列表沿用逐项计数。任务内部的 OCR 业务阶段和旧图片动作共用第二行进度，每次任务结束都会清除该行，避免下一项显示上项的进度。进度仅表示执行位置；最终业务状态仍以任务报告为准。

单项异常向调用方抛出；每日列表记录错误并继续后续项。消费后不递归重放整任务；恢复必须先核对实际结果。旧任务中尚未有界的等待和缺少业务结果核验的场景见[待验证清单](pending-validation.md)。

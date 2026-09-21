# 每日运行日志与中途排查

从原有命令启动即可，完整日常 `daily_task.py`、剧情活动、复刻和礼物独立入口均自动建立 `cache/daily/runs/<时间-pid-随机值>/`。功能由 `pcrscript/run_session.py` 实现，不依赖 Agent 在运行前准备。记录仅存在被忽略的 cache 中。

- `console.log`：Python stdout/stderr 的持续留存（第三方直接写原生句柄的输出不保证捕获）。
- `events.jsonl`：真实时间戳、任务/动作、匹配目标与结果、OCR 文字/坐标/置信度、实际点击与滑动坐标、驱动调用开始/结束。输入操作不记录输入文本，也不转储配置。OCR 坐标为 960×540，驱动坐标为截图实际尺寸。
- `status.json`：PID、心跳、运行/暂停/结束状态、当前步骤、最近操作、截图时间、错误次数、控制请求确认 ID。
- 每五秒至多留一张历史截图，24 张循环保存；最后成功截图另存于内存，异常时立即落盘。每次异常或诊断都创建独立的 `incident-*`，保存最近观察截图、当时仍在环形区的历史截图、异常堆栈与主线程调用栈。历史帧顺序与采集时间查 events 的 frame 事件；旧事件引用的环形文件可能已被替换，须按事件序号取最后一次写入。

异常快照使用**最近成功观察**，不会为取证另起线程操作模拟器。`details.json` 标明 frame_time；截图失败、阻塞或启动前异常时可能没有截图，不能把旧图当故障时刻实时画面。恢复/返回首页前即记录 Robot 捕获的异常；捕获后继续运行的错误也使最终运行状态为 failed、进程返回非零。所有运行记录默认保留；环形区有上限，日志和 incident 不自动清理，按需要归档整个运行目录。

## 控制命令

Windows GUI 通过正式入口 `scripts/desktop.py` 复用同一状态文件与控制协议，另支持协作式 `stop`：驱动边界或公共时钟等待时抛出取消信号，退出后状态为 `cancelled`，取消不会记为错误。暂停状态也可停止；系统调用阻塞时仍需等待返回。CLI 原有暂停/恢复/现场命令保持兼容，GUI 使用见 [图形控制台](desktop.md)。

在仓库根目录执行，命令不连接模拟器。默认仅在唯一活跃运行时自动选择，否则显式添加 `--run <运行目录>`。

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/agent/run_control.py status
./.venv/Scripts/python.exe -X utf8 scripts/agent/run_control.py pause
./.venv/Scripts/python.exe -X utf8 scripts/agent/run_control.py snapshot
./.venv/Scripts/python.exe -X utf8 scripts/agent/run_control.py resume
```

暂停是协作式的：在下一次截图/点击/滑动/输入前确认停下。只有命令确认且 state=paused 才允许 Agent 使用后台驱动查看画面；请求发出后，在确认前可能还有正在执行的操作。默认等确认十秒，超时返回非零，**不等于已暂停**。不并行发送相互冲突的 pause/resume 请求。snapshot 使用独立请求文件，不会取消暂停。

Agent 介入流程：先 status → pause 并核实确认 → snapshot → 读取运行日志/异常目录 → 如需新图才使用已有 `scripts/agent/game.py` → 结束全部探查进程 → resume。优先只读观察；操作页面前先评估恢复位置。每日入口持有进程锁，阻止同一仓库重复启动日常；此锁不授权并行探查，也不覆盖直接调用 DNDriver 的临时脚本。

恢复时重新截图；如果暂停点位于待执行的点击/滑动/输入前，则必须与原观察画面逐像素一致才执行。动画也可能导致保守停止。若画面已改变，记录错误并终止，重新运行任务以从入口重新识别，不能盲目继续旧坐标。暂停发生在截图前则直接获取新图继续。暂停会扣除脚本的等待/战斗/任务超时，但不会暂停游戏自身的战斗、倒计时或活动结束时间。

驱动 120 秒没有完成一次操作，或同一步骤持续 300 秒，会自动保存一次疑似卡住现场。它是排查线索，不自动撤退/点击/杀进程，也不保证发现所有逻辑死循环。若系统调用/GIL 完全卡死，Python 监测线程也可能不运行；心跳陈旧或暂停未确认时不得启动第二个模拟器操作进程。可保留已落盘证据后决定是否结束原进程。

## 根据证据定位

先看 status 与 incident.details 的异常和 owner_stack，再按 events 的时间向前找 wait/action/match/ocr 和最近 driver.begin/end：begin 后没有 end 通常指向驱动阻塞；连续未匹配同时截图出现不同按钮，提示 UI/模板可能变化；OCR 漏字或置信度低时检查原图和识别框；反复返回同一画面则检查导航条件与当前步骤。以上均是线索，未经截图和代码交叉验证不直接断言原因。

## 验证范围

2026-09-21：完整日常671秒正常结束（返回0、finished、errors=0），未复现退出清理异常。运行证据 `cache/daily/runs/20260921-162528-33264-b67a00/`。本次发现任务固定输出目录会覆盖旧报告/关键截图，暂由分析时复制至 `task-evidence/` 保留；正式自动按运行归档尚未实现，已列入 `docs/daily-optimization-plan.md`。暂停/恢复本次未测试。

2026-09-20：离线复现退出阶段 `Exception ignored in atexit callback ... reset_all` / `ValueError: I/O operation on closed file`。颜色输出库在 RunSession 内初始化后保存了日志分流对象，退出时重置终端颜色仍写入已关闭的日志文件。已修复 `_Tee`：日志关闭后仍转发到原控制台，写入/刷新不再访问已关闭的日志；不吞掉其他异常。子进程真实 atexit 回调与诊断回归共 9 项通过。该退出清理异常不代表游戏任务失败，也不会被已结束的 console.log 捕获。

2026-09-19：已完成离线假驱动与真实子进程控制测试（暂停确认、恢复、时间扣除、画面变化拦截、异常现场保留、监测线程栈、输入文本不记录、并发日常互斥）。未为此运行消耗资源的完整日常或制造游戏故障。首次真实日常的暂停/恢复验收步骤见游戏知识库待验证记录。

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s test -p test_run_session.py -v
```

## 2026-09-21 统一 Task 调度补充

新旧任务经 Robot.run_task 执行，新增 task.result 事件与 tasks/<序号>-<任务名>/result.json；新任务的 report.json 和消费截图同目录存放，重复任务不会覆盖。旧任务只记录调度结果，不自动声称资源已核验。先前固定目录覆盖问题已在新任务统一调度链解决，历史路径不搬移。独立入口和完整日常共用配置、Task 和诊断，详见 task-architecture.md。

# Windows 图形控制台

GUI 使用 C# / WPF / .NET Framework 4.8，发布为 Windows x64 便携程序 `PcrDesktop.exe`。GUI 不包含 Python 代码或解释器，不将 Python 打包成二进制；执行时调用选定工程的 Python 入口。源码位于 `desktop/PcrDesktop/`，协议入口为 `pcrscript/desktop.py`。

## 获取与开始使用

GitHub 仓库的 **Actions → Windows GUI → 成功的运行 → Artifacts → PcrDesktop-win-x64** 中可下载打包结果。解压 artifact，再解压其中的 `PcrDesktop-win-x64.zip`，运行 EXE。请完整解压 ZIP 后双击 EXE，旁边的 DLL 和 `.exe.config` 需一起保留。GUI 复用 Windows 的 .NET Framework，不捆绑新 .NET 运行时：Windows 10 1903 及以后版本、Windows 11 自带兼容版本；更旧系统需另装 Framework 4.8。打开 GUI 不需要 Python；执行任务与下载源码需要 Windows x64 Python 3.12 或更高兼容版本，以及 Git。当前依赖安装和 CI 使用 Python 3.12，其他版本需检查依赖兼容性。

1. 首次启动弹出环境引导，必需选择工程目录和包含 `ldconsole.exe` 的雷电安装目录。自动识别已有工程；目录不存在或为空时显示从 GitHub 下载入口，非项目非空目录不允许覆盖。旧工程缺少 GUI 接口时会提示更新。下载默认分支为 `codex/agent-driven-story-events`，后续合并后可改为实际发布分支。
2. 引导自动选择工程内 `.venv/Scripts/python.exe`，也可选择已有解释器；没有环境时点击“创建环境 / 安装依赖”。程序创建 `.venv` 并安装 `requirements.txt`，完成时检查 Python 任务接口。设置记住后不重复弹窗；工程、Python 或雷电路径失效时重新引导，环境页也可手动重新配置。
3. 在“任务配置”页打开现有 YAML，或选择“新建空白配置”。空白配置不带任务和账号；在“配置选项”页填写雷电安装目录，并用表单编辑活动、礼物和驾车游选项。
4. “可用任务”页独立显示当前工程支持的20项任务、任务说明、起始页面要求和参数。无需导入配置即可刷新查看。选择任务后可进入参数编辑并加入当前配置；任务列表支持启用、排序与移除。
5. “保存”生成或更新 YAML；“另存为”生成独立副本，保留源文件及源文件中的账号与其他账号组。默认保存位置 `cache/desktop/profiles/` 被 Git 忽略，也可自行选择路径。顶部下拉列表包含默认配置、该目录的配置和最近打开的配置；选择后点击“加载所选配置”。
6. “执行当前配置”运行已加载配置中全部启用项；运行前保存配置，新配置需选择保存位置，取消保存不会开始整组执行。“执行右侧选中任务”直接传递 GUI 当前运行选项和参数到 Python 内存，不读取用户配置文件、不要求保存，也不生成临时配置文件或修改任务列表。雷电路径使用环境引导中选定的目录，任务参数和其他运行选项可直接编辑。驾车游默认仍为按需任务。

现有多账号格式被保留，GUI 编辑的是第一个任务组，与 `daily_task.py` 的选择规则一致。本版不提供账号登录和多账号组切换。账号密码不会发送到 GUI 配置接口；保存时保留原始 `Accounts` 和其他账号组。禁用项保存在 `Desktop.plan` 中，实际运行的 `Task` 只包含启用项。外部修改了 `Task` 时优先加载外部修改。

任务参数从 Python 已注册任务的运行签名生成，支持布尔、数字、文本和复杂 JSON。公共配置已提供文本、数字和开关表单，复杂对象仍可用 JSON 编辑；不自动执行账号培养、首领试打等操作，示例原有默认开关保持不变。YAML 保存会重新排版、移除注释，并保留 `.bak` 备份；未知配置字段保留。保存前检查文件摘要，外部修改冲突时拒绝覆盖。

## 运行控制与记录

Python 仍通过原有 Robot、Task、DNDriver 执行，GUI 不操作模拟器，不调用 ADB。状态页展示任务、步骤、心跳、错误数、耗时和 stdout/stderr；内存日志有长度上限，完整日志保存在运行目录。

暂停在驱动操作边界确认；“请求已发出”不等于已暂停。恢复沿用原有画面一致性检查。停止使用协作式取消，可中断公共时钟的等待，并从暂停状态退出，终态为 `cancelled`。阻塞的系统调用或网络请求不保证即时停止；控制超时仍显示未确认，不伪装成停止，也不自动启动第二个进程。停止不暂停游戏本身的战斗。

运行状态和结果位于工程的 `cache/daily/runs/<UUID>/`。保存现场只记录已有观察和线程栈，不并行调用模拟器。历史页展示最近100次运行、任务结果和最近日志；“打开记录目录”可查看异常截图和完整证据。状态页会标注心跳失联。重新加载同一工程可接续查看 GUI 启动的未结束运行；旧命令入口的历史记录可浏览，旧格式运行的控制继续使用原命令。

GUI 正常关闭前要求本窗口的操作及任务结束；GUI 意外退出不会自动杀死 Python。若任务卡死或心跳失联，需要通过现有运行诊断确认并处理，不把失联视为已经停止。每个 Windows 会话只打开一个 GUI；现有 Python 运行锁仍按工程目录生效，因此不得从不同工程副本同时操作同一模拟器。

## 源码与环境更新

首次引导和环境页的“下载到新目录”均提供两种范围，并记住选择：

- **仅核心运行文件（默认）**：`pcrscript/`、`images/`、`requirements.txt`。包括 GUI 协议、统一执行逻辑及内置空白配置默认值；无需 `scripts/`、根目录每日入口或示例 YAML。
- **完整仓库**：普通 Git clone，保留当前分支全部文件、仓库历史与远端分支信息，适合开发和使用额外工具。

核心模式使用浅层 partial clone（`--filter=blob:none --no-checkout`）及非 cone sparse checkout 白名单，避免先下载完整文件再删除。隐藏的 `.git` 用于版本检查和更新；运行后生成的 `.venv`、缓存和配置属于本地数据。后续更新保留原有下载范围，修改下载选项只影响新目录，不改动现有工程。

“检查源码版本”显示本地提交。“更新源码”先核对 Python 运行锁、工作区改动和当前分支，再 fetch 并仅允许快进合并；不会 reset 或覆盖本地源码改动。更新后需要安装依赖，再加载配置。配置、缓存和 `.venv` 保留在原目录；GUI 偏好保存在 `%LOCALAPPDATA%/PcrDesktop/settings.json`。

本版更新使用单一 Git 工作目录，尚不提供按版本隔离的依赖环境和自动回滚。下载失败时保留现场；新目录已存在时拒绝覆盖。用户自行提供的 Python、Git 和仓库访问权限需可用。源码更新不自动更新 GUI EXE，GUI 从 Actions 下载新包替换。

## 本地编译和 GitHub Actions

安装 .NET 10 SDK，在项目根目录运行：

```powershell
dotnet build desktop/PcrDesktop/PcrDesktop.csproj -c Release -o artifacts/gui -p:DebugType=None -p:DebugSymbols=false
```

输出为 `artifacts/gui/PcrDesktop.exe`。构建需要 .NET SDK（CI 使用10.x），通过 NuGet 获取 Framework 4.8 编译引用；用户电脑不需要安装该 SDK 或 .NET 10。输出包含 EXE、少量 JSON 依赖 DLL 和 Framework 配置文件。二进制和编译中间文件被 Git 忽略。

`.github/workflows/desktop.yml` 在相关代码 push、PR、`gui-v*` 标签及手动触发时执行：安装 Python 依赖 → 全套离线测试 → 构建 Framework EXE → 隐藏窗口进行 GUI/Python 协议及渲染检查 → 上传 ZIP、SHA256 和渲染证据。另检查运行文件总量不超过5 MB。使用只读仓库权限，不打包账号配置、cache 或 Python 源码，不自动创建 Release。首次 workflow 成功后才能宣称 GitHub 云端构建已验证。

无模拟器的本地 GUI 冒烟检查（程序内部只渲染离屏内容，不显示前台窗口、不修改账号配置）：

```powershell
$p = Start-Process -FilePath artifacts/gui/PcrDesktop.exe -ArgumentList @('--smoke', 'artifacts/gui-smoke.png', ('"' + $PWD.Path + '"'), ('"' + "$PWD/.venv/Scripts/python.exe" + '"')) -PassThru -WindowStyle Hidden
$p.WaitForExit()
$p.ExitCode
```

从内置默认选项开始，检查任务说明、动态参数和公共配置表单，使用 GUI 保存逻辑生成临时配置并重新加载，输出全部六个控制台页面及首次引导的截图；临时配置只含示例数据，位于忽略的 `cache/desktop/smoke/`；异常输出为同路径 `.error.txt`。这不替代真实模拟器日常执行验收。

技术参考：[WPF](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/overview/)、[Windows 内置 Framework 版本](https://learn.microsoft.com/en-us/dotnet/framework/install/versions-and-dependencies)、[setup-dotnet](https://github.com/actions/setup-dotnet)、[Actions 构建产物](https://github.com/actions/upload-artifact)。

## 首页前置条件（2026-09-21）

任务通过 `@register(..., requires_home=True)` 声明首页要求，Robot 的统一调度在执行前自动返回首页，GUI 单项执行与完整配置执行一致。已在首页时只做匹配确认；返回首页最多等待60秒，失败则该任务不开始。只关闭/取消已知弹窗，不自动确认未知弹窗。

旧配置中无参数的 `tohomepage` 分隔项在 GUI 加载和完整列表执行时省略；自定义参数的手动首页任务保留，单独执行 `tohomepage` 也仍可用。当前地图任务 `common_adventure` 不自动回首页；OCR 任务使用自己的页面识别与恢复流程，不强制退出已识别的活动或弹窗。任务说明中显示各自的起始页面要求。

## 启动引导与无配置单任务（2026-09-21）

首次引导仅准备工程、模拟器和 Python 环境，不要求选择 YAML。进入控制台后自动加载任务能力与内存默认选项；配置文件的打开/选择/生成位于任务执行页，属于可选的方案管理。加载配置时目标模拟器仍采用环境引导选择的目录，修改目标请使用“重新配置工程 / 模拟器”。

单任务经标准输入传递 JSON 运行选项，复用 `run_task_with_config()` 与原任务调度；只产生正常运行日志，不生成任务配置文件。缺少雷电路径会在连接设备前停止。离线测试确认无 YAML 读取/写入及调用方选项不被修改。GitHub 核心下载已通过最终 EXE 实测；干净机器安装和模拟器执行仍待实测。

## 下载范围验证（2026-09-21）

正式运行接口为 `pcrscript/desktop.py`，共享执行函数为 `pcrscript/runtime.py`；旧命令入口只做兼容调用。`runtime_defaults.yml` 随核心包提供，无账号数据且任务列表为空。

`test/verify_desktop_runtime.ps1` 使用本地临时 Git 仓库，调用 EXE 内真实下载实现：核心模式检查无关文件既不检出也不获取 blob、生成配置后工作区干净、快进更新保持范围；完整模式确认工具/文档仍在。两个下载目录都运行 GUI 配置生成/重载、任务能力与离屏渲染检查。GitHub workflow 同样执行此验证。它不依赖模拟器或真实账号，也不等同于 GitHub 网络及新机器安装实测。

## 轻量版验证（2026-09-21）

已从 .NET 10 自包含发布迁移为 .NET Framework 4.8。保留全部 WPF 配置与控制界面，任务仍通过 Python 执行。Windows 参数转义、UTF-8 标准输入/输出、异步进程等待、辅助进程超时终止和目录选择使用兼容实现。下载范围设置仍保留。

148项 Python 离线测试通过；Framework 编译零警告/零错误。两种下载模式、核心范围快进更新、无关 blob 排除、任务能力加载、配置生成/重载、中文与特殊字符参数传递、超时辅助进程终止、全部六页及首次引导离屏渲染检查通过。本次未启动模拟器。

本地可测试包：`artifacts/PcrDesktop-win-x64-light.zip`；程序：`artifacts/gui-light/PcrDesktop.exe`；校验：`artifacts/SHA256SUMS-light.txt`。EXE 约114 KB，全部二进制约1.5 MB，压缩后小于1 MB。此前约140 MB 的自包含版本不再作为默认发布。证据：`artifacts/gui-light-smoke.png*`。GitHub workflow 已同步为轻量构建与5 MB大小上限，但首次云端运行仍需提交推送后触发。

## 收尾与后续接续（2026-09-21）

- GUI 名称按页面区分：礼物箱领取 `get_gift`、首页任务领奖 `get_quest_reward`；剧情活动领奖兑换已合并到 `campaign_clean`，不再单独显示 `campaign_reward_exchange`。礼物处理只有一个注册任务；`scripts/daily/gifts.py` 是同一实现的命令包装，不新增任务。用户当前配置保留原顺序与参数，未合并不同页面的消费/领奖。
- 根目录只保留入口、项目规则、README 和统一 `requirements.txt`。示例配置迁移到 `docs/examples/daily.example.yml`，旧多账号入口到 `scripts/legacy/multi_account.py`，历史说明到 `docs/legacy-features.md`；删除 `snip_tool.py`、`test.py` 和重复依赖清单。根目录实际账号配置仍被忽略。
- 未安装 Python 时，引导提供官网下载按钮、安装说明和检测按钮；推荐 Python 3.12 x64。检测跳过 Windows Store 占位路径。创建环境会先找可用解释器，在项目 `.venv` 安装唯一依赖清单，联网失败给出可重试提示。`pcrscript/desktop.py environment` 仅依赖标准库，可在完全没装项目依赖时报告缺失/版本不匹配。启动、完成引导和任务执行前检查运行环境。
- 状态输出保留中文；GUI 同时解码旧日志中嵌套的 JSON 字符串，不对任意路径做 Unicode 替换。操作显示为“操作：…”而非 `\u` 转义。
- 验证入口：Python 全套离线回归；`test/verify_desktop_runtime.ps1` 检查两种下载、核心更新范围、状态中文显示、Python 缺失引导与检测、进程通信和七页离屏渲染。需正常 Windows 权限以终止测试自己创建的超时辅助进程。未以真实游戏操作验收，不得将离线结果描述为模拟器实测。

发布状态与 GitHub 构建链接见 `docs/desktop-handoff.md`。后续 Agent 先读本文件、项目目录说明和游戏待验证记录；不要再下载或捆绑 .NET 10 运行时，不要把 scripts 重新引入核心运行依赖。

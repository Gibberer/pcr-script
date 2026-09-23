# GUI 收尾接续（2026-09-21）

## 2026-09-22 日常与专项工作区

新增每日日常/按需专项分类与独立运行表单，启动默认加载有效的上次配置或工程 daily_config.yml；安装依赖后同样恢复当前配置。旧配置中的专项保留并标注，新增日常只能选日常分类。专项仅使用对应配置段与 Extra，表单修改不会保存到日常。攻略来源搜索由具体战斗任务内部调用。活动情报可调度的首通仍属于日常类别。具体操作见 desktop.md。

192 项 Python 离线测试通过，Framework 构建零警告/零错误；隐藏离屏检查验证分类、默认配置回落、专项选项隔离、配置保存重载和进程协议。六页常规尺寸、两个紧凑尺寸及环境引导共九张渲染图，已查看日常/专项布局；证据 artifacts/gui-workspaces-final.png*，日志 cache/build/gui-workspace-tests.log。便携包 artifacts/PcrDesktop-win-x64-workspaces.zip。本轮未操作模拟器、未修改实际账号配置；本版尚未进行真实 GUI 点击启动游戏验收，也未推送或发布。

## 当前实现

本轮功能开发到此结束。GUI 为 C# WPF / .NET Framework 4.8，复用较新 Windows 10/11 的系统运行时；便携包保留 EXE、DLL 和 .exe.config，全部运行文件约1.5 MB。Python 始终源码执行。

- 首次工程/雷电/Python 引导；无 Python 提供官网下载与检测，项目环境按统一 requirements.txt 安装依赖。缺依赖、安装失败和版本不符均提示处理方式。
- 下载默认仅 pcrscript/、images/、requirements.txt、desktop/runtime_defaults.yml；用户可选完整仓库。核心模式 partial clone + sparse checkout，更新保持范围。
- GUI 配置新建/编辑/保存/另存为，20项任务能力说明，单项执行无需配置文件，需首页任务隐式导航，状态/历史/协作控制。
- 活动领奖/兑换包含在 campaign_clean，按用户要求删除独立 campaign_reward_exchange。旧配置若有此项需移除；不自动转换为会扫荡的任务。get_gift 只处理礼物箱，与首页任务领奖名称明确区分。
- 中文 action 状态在 Python 输出及 GUI 旧日志解析两端修复，GUI 展示为中文操作详情。
- 删除 snip_tool.py、test.py，合并 requirements；示例在 docs/examples/daily.example.yml，历史文档在 docs/legacy-features.md，多账号旧入口在 scripts/legacy/multi_account.py。保留 daily_task.py/.bat 兼容入口。

## 验证与复现

148项离线 Python 测试通过，Framework 构建零警告/零错误。两种下载模式、无关 blob 排除、核心更新范围、任务注册表/配置生成与重载、中文状态、Python 缺失提示/现有解释器检测、UTF-8 与特殊字符进程参数、超时辅助进程终止、七页离屏渲染均通过。本轮未操作模拟器或修改实际 daily_config.yml。

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s test -p 'test_*.py'
dotnet build desktop/PcrDesktop/PcrDesktop.csproj -c Release -o artifacts/gui -p:DebugType=None -p:DebugSymbols=false
./test/verify_desktop_runtime.ps1
```

本地 .NET SDK 在忽略目录 cache/build/dotnet；可用它替换 dotnet 命令，并设置 DOTNET_CLI_HOME=cache/build/cli、NUGET_PACKAGES=cache/build/nuget。离线 UI 验证需要正常 Windows 权限以终止测试自建的超时子进程，沙箱可能拒绝 taskkill；无需管理员操作模拟器。

本地证据 artifacts/gui-final-smoke.png*，回归日志 cache/build/final-tests.log。最终 GUI 从 GitHub 已推送分支实际下载核心文件并运行接口/离屏验证通过，证据 artifacts/gui-github-smoke.png*，仅检出 pcrscript、images、requirements.txt（另生成本地 cache）。最终本地包 artifacts/PcrDesktop-win-x64-final.zip（不提交产物）。GitHub workflow 名 Windows GUI，上传 PcrDesktop-win-x64 和 GUI-smoke-evidence；只读仓库权限，运行文件限5 MB。

## 发布状态

分支 `codex/agent-driven-story-events`。功能提交 `db39c1818441be8c610c1f122c1987c29ef5fe7c`，验证提交 `bd28041cc0dc761a1cb8f005eecf3b5d1aa64ee4` 已推送。首次未触发因仓库 Actions 未启用；用户启用后重推已成功。

[Windows GUI 构建 #35596647901](https://github.com/Gibberer/pcr-script/actions/runs/35596647901) 最终状态 **completed / success**，对应 `bd28041`。依赖安装、148项回归、Framework 编译、两种下载与 GUI 离屏验证、5 MB体积检查、ZIP/SHA256 打包和上传全部成功。已通过 GitHub API 核对并成功下载 artifact：

- `PcrDesktop-win-x64`：artifact ID `10636946597`，566166字节（约553 KiB），包含 GUI ZIP 与 SHA256。
- `GUI-smoke-evidence`：artifact ID `10637510615`，824317字节，含渲染证据。
- artifact 默认到期时间 2026-12-20；到期后重新运行 workflow。没有发布 GitHub Release。

以上为 2026-09-21 的发布检查点；后续改动与验证见文末，不能沿用这次云端成功证明新改动已通过。

## 留给后续 Agent

先读 AGENTS.md、游戏知识 README/characters/pending-validation，再按 docs/project-structure.md 与 docs/desktop.md 接续。不要恢复独立活动领奖入口，不重复维护 requirements，不把 scripts/ 引入精简运行依赖，不捆绑 .NET 10 运行时。

待自然使用验证：干净 Windows 机器的官网 Python 安装/目录选择/网络失败引导，以及正常日常中的首页导航、礼物处理、暂停恢复与停止。离线通过不代表这些场景实机通过；游戏首通、首领等原有待验证项继续保留，默认开关不变。不得为收尾重复消费、测试战斗或制造满仓。

## 2026-09-22 深域与通用攻略搜索

Python目录新增 `abyss_push` 按需专项；通用攻略搜索现为内部共享模块，任务链接分别放在 `Abyss.source_urls`、`Dungeon.source_urls`，GUI不列出来源搜索任务。WPF补充属性、失败上限和隔离浏览器会话选项中文标签。正式来源搜索新增根requirements中的Playwright，使用系统Edge headless，不要求用户额外安装Node。深域实战与待验证边界见game-knowledge/abyss.md。提交 `d250b84` 后使用忽略目录中的本地 .NET 10 SDK 重新构建，Framework GUI 零警告、零错误；后续工作区目录调整仍需重新验证。


## 2026-09-23 PR 准备与 GUI 交互收尾

- 日常添加改为独立窗口，已选行只编辑该行参数；校验失败阻止静默丢失，增加未保存提示、配置切换保护、单击启用及排序/删除状态。
- 日常选项分组折叠；专项表单隔离；运行按钮随运行/暂停状态启用；历史空状态、环境设置分组与紧凑布局完成。统一字体、按钮和页签，未新增游戏操作逻辑。
- README 改为 GUI 下载优先；`desktop.md` 为图文使用指南，`tasks.md` 分日常和单项，`releases.md` 说明合并后的版本发布。截图均由合成数据离屏渲染，不含账号数据。
- 发布工作流补标签发布 job：仅 push `gui-v*`、标签提交已合入 `master`、测试/构建通过且 SHA256 匹配时创建 Release，不覆盖既有发布。GUI 新安装默认来源为 `master`；旧版默认开发分支在官方仓库上迁移到 `master`，自定义分支保留。
- 本地 258 项 Python 回归通过，Framework 编译零警告/错误；两种下载、核心范围更新、进程通信、配置保存重载、添加/编辑/无效参数/排序移除、运行按钮状态与离屏渲染通过。证据 `cache/agent/pr-ready-tests.log`、`artifacts/gui-pr-package.png*`。
- 本地待审包 `artifacts/PcrDesktop-win-x64-pr-review.zip`；工作区改动尚未提交/推送，本轮未创建 PR、合并或发布标签。Release job 尚待合并后首次标签运行；干净 Windows 安装和正常游戏任务控制仍待自然使用验收。
- 视频解析停在明确的部分支持状态，详见 [video-strategies.md](video-strategies.md)。Agent 接管必须复核脚本报告与原始证据；不要宣称完整替代人工处理任意视频。


### 2026-09-23 实际窗口复核与列表修正

用户指出日常列表未对齐、源码下载需指向主分支，并要求实际运行确认。日常表格现统一表头/单元格内边距、文字垂直居中与省略提示，启用列居中；右侧单项执行按钮固定在编辑区底部。`Settings.Load` 将官方仓库旧版默认 `codex/agent-driven-story-events` 迁移到 `master`，保留自定义分支。首次引导的分支框实际显示 `master`。

验证使用 `PcrDesktop.exe --live-check <证据前缀> <工程目录> <Python>` 启动真实 WPF 窗口：窗口完成布局，打开添加任务对话框并通过按钮确认，再检查专项及首次引导。实际窗口截图在忽略的 `artifacts/gui-live-check.png*`。这项检查没有启动模拟器或执行游戏任务。核心/完整下载、配置及离屏检查也再次通过，证据 `artifacts/gui-aligned-smoke.png*`。Framework 编译零警告/错误。本地待审包更新为 `artifacts/PcrDesktop-win-x64-pr-review.zip`，不提交二进制。

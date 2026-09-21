# GUI 收尾接续（2026-09-21）

## 当前实现

本轮功能开发到此结束。GUI 为 C# WPF / .NET Framework 4.8，复用较新 Windows 10/11 的系统运行时；便携包保留 EXE、DLL 和 .exe.config，全部运行文件约1.5 MB。Python 始终源码执行。

- 首次工程/雷电/Python 引导；无 Python 提供官网下载与检测，项目环境按统一 requirements.txt 安装依赖。缺依赖、安装失败和版本不符均提示处理方式。
- 下载默认仅 pcrscript/、images/、requirements.txt；用户可选完整仓库。核心模式 partial clone + sparse checkout，更新保持范围。
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

本地证据 artifacts/gui-final-smoke.png*，回归日志 cache/build/final-tests.log。最终本地包 artifacts/PcrDesktop-win-x64-final.zip（不提交产物）。GitHub workflow 名 Windows GUI，上传 PcrDesktop-win-x64 和 GUI-smoke-evidence；只读仓库权限，运行文件限5 MB。

## 发布状态

分支 codex/agent-driven-story-events。本次提交推送后核对同一提交的 workflow 成功状态、全部步骤和 GUI ZIP/SHA256 产物，再补充构建链接。本段待云端结果回填。

## 留给后续 Agent

先读 AGENTS.md、游戏知识 README/characters/pending-validation，再按 docs/project-structure.md 与 docs/desktop.md 接续。不要恢复独立活动领奖入口，不重复维护 requirements，不把 scripts/ 引入精简运行依赖，不捆绑 .NET 10 运行时。

待自然使用验证：干净 Windows 机器的官网 Python 安装/目录选择/网络失败引导，以及正常日常中的首页导航、礼物处理、暂停恢复与停止。离线通过不代表这些场景实机通过；游戏首通、首领等原有待验证项继续保留，默认开关不变。不得为收尾重复消费、测试战斗或制造满仓。

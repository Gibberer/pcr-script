# PCR 任务控制台

面向《公主连结》国服的本地自动化工程：用 GUI 配置日常、执行单项任务和查看记录，也保留 Python 命令行入口。工程提供共享识别能力、运行证据与 Agent 协作约定；正式任务由脚本独立执行。

## 从 GUI 开始

**无需提前 clone 仓库。** 下载 GUI 后，按程序内的引导准备工程和运行环境。

1. 打开 [GitHub Releases](https://github.com/Gibberer/pcr-script/releases)，下载 `PcrDesktop-win-x64.zip`，完整解压并运行 `PcrDesktop.exe`。请保留同目录 DLL 和 `.exe.config`。尚未发布 Release 时，可在 [Windows GUI 构建](https://github.com/Gibberer/pcr-script/actions/workflows/desktop.yml)的成功记录中下载同名 Artifact。
2. 按引导选择一个空工程目录，点击“从 GitHub 下载项目”。默认只下载运行所需文件；也可以选择已有工程。
3. 选择雷电安装目录，检测 Python，再点击“创建环境 / 安装依赖”。任务运行需要 Windows x64、Python 3.12+ 和 Git；引导提供 Python 下载与检测入口。雷电使用后台驱动，无需 ADB；游戏需事先登录，当前实机验证尺寸为 **960×540**。
4. 在“每日日常”点击“＋ 添加任务”，选择任务及参数。选中列表中的项目即可修改参数、启用或调整顺序，点击“保存配置”，再“开始今日日常”。
5. 地下城、深域、角色培养等工作从“按需专项”执行；进度、暂停、停止和证据在“运行状态 / 运行记录”查看。

![日常任务配置](docs/images/gui-daily.png)

- [GUI 详细指南](docs/desktop.md)：首次使用、添加与编辑、专项、运行控制及截图。
- [任务指南](docs/tasks.md)：可配置的日常任务、单项任务用法和复杂任务逻辑。

地下城和深域的来源搜索、头像建库与部分视频解析已经接入正式程序，但**任意视频的完整培养要求、操作时序及多队路线规划尚未全部完成**。未知字段会保留证据并阻止把不完整来源当作完整作业；详情见[视频解析范围与交接](docs/video-strategies.md)。本地试打、升星和秘石兑换默认关闭。

## 命令行使用

安装 Python 3.12+ x64 和 Git，在终端执行：

```powershell
git clone https://github.com/Gibberer/pcr-script.git
cd pcr-script
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item docs/examples/daily.example.yml daily_config.yml
```

编辑 `daily_config.yml` 中的 `Extra.dnpath` 和 `Task` 列表，然后运行完整日常：

```powershell
./.venv/Scripts/python.exe -X utf8 daily_task.py
```

按需执行某个注册任务，例如礼物领取：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py get_gift
```

完整日常会启动雷电与游戏；单项任务通常要求模拟器和游戏已经打开。任务参数、来源配置及运行范围见[任务指南](docs/tasks.md)。实际配置、头像、作业与运行证据都保存在本地忽略目录，不应提交到仓库。

## 支持范围与扩展

目前支持 **Windows 上的雷电模拟器，游戏画面使用 960×540 分辨率**。其他模拟器、设备或分辨率尚未验证，需要适配截图、输入、坐标和界面识别，并在目标设备上检查结果。

想支持其他设备或开发新任务，可以在常用的 AI 编程 Agent 中选择本项目目录，直接描述目标。仓库已经整理了[游戏规则、页面坐标和导航路径](docs/game-knowledge/README.md)，也保留了已有任务和[待验证场景](docs/game-knowledge/pending-validation.md)，可以帮助 Agent 接续开发，减少重新摸索页面的工作。例如可以要求它“在当前工程新增一个按需任务，并根据知识库核对页面和执行边界”。新设备和新任务仍需在实际游戏中验证。

开发约定见 [AGENTS.md](AGENTS.md)，代码位置见[项目结构](docs/project-structure.md)。运行问题可查[运行诊断](docs/run-diagnostics.md)；GUI 构建见[发布说明](docs/releases.md)。

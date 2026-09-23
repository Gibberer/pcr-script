# PCR 日常脚本

这是一个用于《公主连结》国服的本地自动化项目。打开 Windows GUI，完成工程、Python 和设备连接的基础设置后，就能运行预设的日常任务；也可以按需单独执行地下城、深域等专项。喜欢命令行的话，同一套任务也能从终端运行。

## 用 GUI 跑日常

1. 从 [GitHub Releases](https://github.com/Gibberer/pcr-script/releases) 下载 `PcrDesktop-win-x64.zip`，完整解压后打开 `PcrDesktop.exe`。
2. 跟随首次引导选择工程目录、下载运行文件、配置设备连接，并准备 Git、Python 和依赖。使用雷电时填写安装目录；使用 ADB 时留空雷电目录，并先让 Android 设备完成授权。游戏需要事先登录。
3. 进入“每日日常”，点击“开始今日日常”。运行进度和结果可在“运行状态 / 运行记录”查看。

![每日日常界面（示例配置）](docs/guides/images/gui-daily.png)

默认列表包含日程、竞技场、调查、活动日常、快捷扫荡、商店和领奖等任务。它会使用游戏里已有的日程安排和扫荡预设，其中快捷扫荡默认使用预设 2；想调整执行内容或顺序时，再到“每日日常”编辑。已有的 `daily_config.yml` 或上次选过的配置会继续优先加载，不会被默认列表覆盖。

地下城首通、深域推进和角色培养在“按需专项”中运行。首次设置和配置编辑的细节见 [GUI 指南](docs/guides/desktop.md)，各任务的执行范围见 [任务指南](docs/guides/tasks.md)。

## 命令行

安装 Windows x64 Python 3.12+ 和 Git 后，在终端准备环境：

```powershell
git clone --depth 1 https://github.com/Gibberer/pcr-script.git
cd pcr-script
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
```

命令行与 GUI 共用根目录的 `runtime_defaults.yml`。先在其中配置 `Extra.dnpath`（雷电），或留空并连接已授权的 ADB 设备；连接多个 ADB 设备时填写 `Extra.adb_serial`。然后运行日常：

```powershell
./.venv/Scripts/python.exe -X utf8 daily_task.py
```

如果已有 `daily_config.yml`，程序会优先使用它。也可以用 `--config <文件>` 指定自己的配置；[示例配置](docs/guides/examples/daily.example.yml)适合用来了解参数。

单独运行已注册的任务，例如领取礼物：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py get_gift
```

## 运行范围

目前游戏任务在 **Windows 雷电、960×540 画面**下有实机验证。项目也支持 ADB 连接，但其他 Android 设备、分辨率和界面布局仍需要逐项验证。地下城与深域的攻略搜索和部分视频解析已接入正式程序；遇到无法确认的角色、培养或路线时，任务会留下证据并停止不确定的战斗。[任务指南中的适用范围](docs/guides/tasks.md#地下城与深域的来源处理)记录了当前边界。

账号配置、头像、攻略和运行证据留在本地，不要提交到仓库。

## 开发

本项目对 AI Agent 友好。把常用 AI Agent 的工作目录设为本项目目录，直接描述要开发的新任务或需要适配的设备即可；仓库已整理游戏知识和工程约定，供 Agent 接续工作。使用 GUI 下载项目时选择“完整仓库”，即可在同一目录中边开发边使用 GUI。

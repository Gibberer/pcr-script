# 命令行使用指南

GUI 用户无需执行本页命令，直接按 [GUI 指南](desktop.md) 一键准备环境即可。本页适用于希望用终端运行或开发的用户；需要完整仓库，GUI 的“仅核心运行文件”不包含命令行入口。

## 1. 准备环境

安装 [Python 3.12 x64](https://www.python.org/downloads/windows/)（安装时勾选 PATH）和 [Git for Windows](https://git-scm.com/downloads/win)，重新打开 PowerShell，在想保存项目的位置执行：

```powershell
git clone --depth 1 https://github.com/Gibberer/pcr-script.git
cd pcr-script
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements.txt
./.venv/Scripts/python.exe -m pip check
```

后续命令都在项目根目录运行。直接使用 `.venv/Scripts/python.exe`，无需激活虚拟环境或修改 PowerShell 执行策略。若已通过 GUI 下载完整仓库并准备环境，可直接使用该工程的 `.venv`，跳过以上步骤。

## 2. 配置设备和任务

复制共用默认配置为自己的本地配置，不直接修改默认文件：

```powershell
Copy-Item runtime_defaults.yml daily_config.yml
notepad daily_config.yml
```

已有 `daily_config.yml` 时跳过复制。找到 `Extra` 段，按设备修改：

```yaml
# 雷电：路径可用正斜杠，避免 YAML 中反斜杠转义
Extra:
  dnpath: 'D:/leidian/LDPlayer9'
```

或使用手机：先准备 [Android Platform Tools](https://developer.android.com/tools/releases/platform-tools)，开启 USB 调试、连接数据线并授权电脑，然后配置：

```yaml
Extra:
  dnpath: ''
  adb_path: 'C:/Android/platform-tools/adb.exe'
  adb_serial: ''  # 多设备时填写 adb devices 输出的目标序列号
```

只修改原配置中对应字段，保留 `Extra` 的其他选项和其他配置段。雷电需设置为 960×540 并启动；手机连接及排错见 [设备准备](desktop.md#设备准备)。手机和其他布局仍需验证。

登录游戏并进入首页。核对 `Task` 列表、日程表、扫荡预设和各项消费选项；参数说明见 [任务指南](tasks.md)，其他写法见 [示例配置](examples/daily.example.yml)。

## 3. 运行

完整日常：

```powershell
./.venv/Scripts/python.exe -X utf8 daily_task.py --config daily_config.yml
```

单独执行礼物领取（默认暂不领取体力）：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py get_gift --config daily_config.yml
```

不传 `--config` 时，优先使用 `daily_config.yml`，没有时使用根目录 `runtime_defaults.yml`。同一设备不要同时运行 GUI 和 CLI 任务。记录位于 `cache/daily/runs/`；查看任务回执和未完成原因，不能只凭进程退出判断目标完成。

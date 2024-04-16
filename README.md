## 前言
> 该脚本为自用脚本，主要用于清日常。

实现方式基于Open CV模板匹配，模板图基于960x540的设备, 对于其他分辨率识别效果不一定好(可能不能正常完成操作)。

## 一点变化
该脚本工程是在国服开放初期创建的，目前在四周年版本中已经由官方支持了自动任务（不幸的是我还在玩这个游戏）。考虑现有工程中有大量无效或无价值的任务代码，所以决定对工程进行一些精简，现在它将变得只专注于一键清理日常。

## 使用引导

* 安装Python3环境，访问[Python官网](https://www.python.org/)安装
* 使用git clone或在网页上下载本项目到电脑中解压缩
* 在命令行中执行以下命令安装项目所需依赖
  ```cmd
  pip install opencv_python numpy pywin32 PyYAML
  ```
* 设置配置文件：修改[_dialy_config.yml](_dialy_config.yml)中的雷电模拟器路径，之后将该文件重命名为**dialy_config.yml**。
  * 如果是其他模拟器可以不设置路径，不过需要保证本机ADB命令可用，脚本会尝试使用ADB命令与设备交互，当然还请注意保持模拟器分辨率为960x540。
* 执行[dialy_task.bat](dialy_task.bat)或[dialy_task.py](dialy_task.py)来启动脚本程序。
  * 运行后会按如下方式进行:启动模拟器->启动游戏->执行脚本任务
---
* 使用雷电模拟器多开注意模拟器标题不要改，并且要保证模拟器标题`雷电模拟器-1`这个后面的`-数字`要和多开器里显示的序号一致
* dialy_task近支持单账号并切已登录，如果需要多账号可以参考[main.py](main.py)，这里会缺少对时限任务的判断，请自行判断。

## 关于任务内容

该部分请查看[_daily_config.yml](_daily_config.yml)文件中的任务列表部分，脚本会按其中所列顺序依次执行每个任务条目，关于每个任务条目的用途也请看注释部分。

### 关于时限任务

时限任务会在[dialy_task.py](daily_task.py)中进行判断，如果对应任务的活动当前未开放，则会将配置的任务条目废弃掉不允执行。


## 前言
> 该脚本为自用脚本，主要用于清日常。

实现方式基于Open CV模板匹配，模板图基于960x540的设备, 具体对设备支持情况见[设备支持情况](explanation.md#设备支持情况)。

## 使用引导

* 安装Python3环境，访问[Python官网](https://www.python.org/)安装
* 使用git clone或在网页上下载本项目到电脑中解压缩
  ```cmd
  git clone --depth 1 git@github.com:Gibberer/pcr-script.git
  ```
* 在命令行中执行以下命令安装项目所需依赖
  ```cmd
  pip install opencv_python numpy pywin32 PyYAML
  ```
* 设置配置文件：修改[_daily_config.yml](_daily_config.yml)中的雷电模拟器路径，之后将该文件重命名为**daily_config.yml**。
  * 如果是其他模拟器可以不设置路径，不过需要保证本机ADB命令可用，脚本会尝试使用ADB命令与设备交互，当然还请注意保持模拟器分辨率为960x540。
* 执行[daily_task.bat](daily_task.bat)或[daily_task.py](daily_task.py)来启动脚本程序。
  * 运行后会按如下方式进行:启动模拟器->启动游戏->执行脚本任务
---
* dialy_task仅支持单设备单账号并且处于已登录状态，如果需要多账号多设备可以使用[main.py](main.py)。不过在该文件中缺少对时限任务的判断，需要注意配置文件中的任务组合方式。
* 部分任务需要依赖冒险图中的角色形象，默认使用6星佩可莉姆。如果是其他角色可以在游戏内冒险地图界面截取其中角色图像中的一部分（最好是脸部，不要截取到地图背景），将新截取的图片替换掉[images/character.png](images/character.png)这个图片即可。

## 关于任务内容

本条目可以查看[_daily_config.yml](_daily_config.yml)文件中的任务列表部分，脚本会按其中所列顺序依次执行每个任务条目，具体任务条目的用途可以留意文件中的注释部分。
如果想获知该项目支持的所有任务可以查看[tasks.py](pcrscript/tasks.py)，如果需要执行单个任务可参考[test.py](test.py)。

### 关于时限任务

时限任务会在[daily_task.py](daily_task.py)中进行判断，如果对应任务的活动当前未开放，则会将配置的任务条目废弃掉不允执行。

---
[其他说明](explanation.md)


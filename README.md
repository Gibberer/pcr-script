## 介绍
> 自用脚本：用来清清日常

基于Open cv 模板匹配的脚本，模板图基于960x540的设备。对于其他分辨率识别效果不一定好(可能不能正常完成操作)。

## 已有能力

> 农场还差个踢人和捐赠装备吧，暂时没需求

主线图支持进度

- [x] 主线普通图支持1-1到4-5 15-10到15-14
- [x] 主线困难图支持1-1到21-3
- [x] 主线图剧情引导跳过支持1-3至2-12

***
- [x] 增加地下城boss队伍能力，支持选择boss队伍的编组，并支持选择1~10的队伍讨伐boss
- [x] 增加脚本用于大号清理日常
- [x] 增加清地下城副本得能力
- [x] 竞技场/公主竞技场
- [x] 圣迹调查
- [x] 探索
- [x] 公会战
- [x] 扫荡普通或困难图
- [x] 行会点赞
- [x] 地下城Normal图/可以选择支援/可以中途放弃（农场相关）
- [x] 领取公会小屋体力
- [x] 购买体力
- [x] 支持兰德索尔杯活动
- [x] 自动抽取免费十连功能
- [x] 申请加入工会功能（农场相关）
- [x] 自动强化前五个角色
- [x] 购买1/10/20次mana功能
- [x] 支持使用win32api对模拟器进行截图（只支持雷电模拟器）
- [x] 实名认证（只支持雷电模拟器）
- [x] 关闭战斗动画
- [x] 领取任务奖励
- [x] 多设备登录及切换账号

## 使用引导

* 操作需要依赖adb命令，请确保adb命令可用。如何安装可以百度搜索关键字“安装adb”
* 安装Python3环境，访问[Python官网](https://www.python.org/)安装
* 使用git clone或网页下载本项目到电脑上
* 执行以下命令安装项目所需依赖
  ```cmd
  pip install opencv_python matplotlib numpy pywin32 PyYAML
  ```
* 在项目根目录创建`config.yml`文件，根据yaml语法配置账号信息及需要做的任务模块，具体可参考[sample.yml](sample.yml)这个文件
* 执行脚本之前，首先打开模拟器并打开游戏界面停留在欢迎页面
* 在当前目录cmd中执行以下命令启动脚本
  ```cmd
  python main.py
  ```
---
* 使用雷电模拟器多开注意模拟器标题不要改，并且要保证模拟器标题`雷电模拟器-1`这个后面的`-数字`要和多开器里显示的序号一致
* 账号中风控之后，登录之后会出现极验的图形验证码，这块还没有做自动化处理。目前需要人工手动处理

## 配置信息

配置默认的账号及需要做哪些任务等信息，需要在工程目录下创建`config.yml`的文件，具体可参考根目录下[sample.yml](sample.yml)文件。清日常的话，参考`sample_daily_config.yml`文件。

```yaml
# 这个是用于清日常的配置文件
Accounts: #存账号信息
  -
    account: 'YourAccount'
    password: 'YourPassword'
Extra:
  dnpath: 'N:\dnplayer2' # 雷电模拟器的安装目录
Task: #配置执行任务,配置任务名称，如果需要传入参数在下面增加参数，可以根据不同的账号序号配置任务。
      #账号会执行小于等于并且离它最近的序号的任务列表
  1: #配置账号大于等于1的进行以下操作
     #最好每个任务结束后设置tohomepage，因为每个任务都是按照当前在首页的情况执行的
    -
      - guild_like # 点赞行会成员
    # 下面注释部分用于有免费10连的时候用
    # 这里没判断是否是免费的十连，所以第二个参数最好不要传True
    # 如果当前没有免费的十连的话就直接把钻石花光了
    # - 
    #   - tohomepage
    # -
    #   - choushilian #抽取免费十连
    #   - False #是否抽取所有免费十连
    -
      - tohomepage
    -
      - normal_gacha #普通扭蛋10连
    -
      - tohomepage
    -
      - get_quest_reward
    -
      - get_power #去公会之家领体力
    -
      - arena #打一把竞技场
    -
      - tohomepage
    -
      - princess_arena #打一把公主竞技场
    -
      - tohomepage
    -
      - explore #探索
    -
      - tohomepage
    -
      - research #圣迹调查
    -
      - tohomepage
    -
      - dungeon_saodang  #扫荡地下城
      - 5 # 极限难度地下城
      - 1  #使用编号1队过小怪
      - '4' # 选择编组4过boss
      - '1,2,3,4,5,6,7,8,9,10' #使用上面选择的编组中编号1到10队过boss，小队之间用','分割
      - False # 结束后是否退出地下城，在无法完成地下城时使用
    # 下面部分用于活动期间清体力
    # -
    #   - tohomepage
    # -
    #   - activity_saodang  # 清活动图的日常，由于每次活动不一样，该任务每次活动更新一次做支持
    #   - True # 是否刷活动困难章节和高难boss
    #   - True # 是否将剩余体力花费在活动普通章节上
    -
      - tohomepage
    - 
      - saodang_hard  #过困难章节把体力用光，这里判断没体力后会自行终止
      - 60 # 开始关卡 60对应 20-3
      - 1  # 结束关卡
    -
      - tohomepage
    -
      - get_quest_reward
    -
      - tohomepage
    -
      - get_gift #领取礼物
```

## 其他

* ADB默认不支持中文输入，中文输入使用的是雷电模拟器的接口。所以如果要使用实名认证功能，需要使用雷电模拟器并传入雷电模拟器的安装目录。**并且由于使用Windows应用程序的命令，会触发防火墙。可以关闭后使用，或者手点下允许。**
* win32api带来的提升还是很高的，使用win32api截图时间平均在0.003秒左右，而使用adb截图耗时浮动在1-2秒。由于win32api的方式需要获取模拟器的窗口信息，这个需要根据模拟器来适配。
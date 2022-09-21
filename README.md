## 介绍
> 该脚本为自用脚本，主要用来清清日常。
> 目前脚本的意义就是定时执行批处理任务`daily_task.bat`把今天日常清下
> 所以会有下面几个问题：
> 1. 脚本能运行的范围，只保证当前在用的功能可以通（目前就是清日常），老的功能很可能就不能用了
> 2. 不存在稳定版本，所有的bug修复都在第二天跑脚本的时候验证。所以最新的提交并不一定解决了问题
> 3. 如果发现问题的话可以提ISSUE，有时间的话会进行修复（比如一些功能我现在不用所以也发现不了bug）

基于Open cv 模板匹配的脚本，模板图基于960x540的设备。对于其他分辨率识别效果不一定好(可能不能正常完成操作)。

## 已有能力

主线图支持进度：
<s>
- [x] 主线普通图支持1-1到4-5 15-10到15-14
- [x] 主线困难图支持1-1到36-3
- [x] 主线极难图支持18-1到? (同步主线困难图最后章节)
- [x] 主线图剧情引导跳过支持1-3至2-12</s>

由于游戏提供了快速扫荡工具，这部分内容不再使用，所以不再处理新图。

***
任务支持列表：

- [x] 清除所有未读剧情（包含主线、角色和公会，特别部分由于执行逻辑不一样这里不做处理）
- [x] 增加使用游戏内置扫荡工具的方式
- [x] 自动过新图及活动新图，详情见[自动过图功能说明](自动过图功能说明.md)
- [x] 露娜塔扫荡
- [x] 商店购买（支持重置次数和购买装备数量小于一定值的装备）
- [x] 打轴，独立模块见[autobattle](autobattle/)
- [x] 清地下城副本
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
  如果使用打轴功能（目前无）需要依赖ocr库并且在配置文件开启ocr功能，这里使用[easyocr](https://github.com/JaidedAI/EasyOCR)。
  注意：当第一次使用easyocr时需要下载模型数据
  ```cmd
  pip install easyocr
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

## 直接执行指定任务

可以通过自行编写代码的方式不使用配置文件，直接执行任务。代码可以参考[sample_run_single_task](sample_run_single_task.py)

## 配置信息参考

配置默认的账号及需要做哪些任务等信息，需要在工程目录下创建`config.yml`的文件，具体可参考根目录下[sample.yml](sample.yml)文件。清日常的话，参考[sample_daily_config.yml](sample_daily_config.yml)文件。

```yaml
# 这个是用于清日常的配置文件
Accounts: #存账号信息
  -
    account: 'YourAccount'
    password: 'YourPassword'
Extra:
  dnpath: 'N:\dnplayer2' # 雷电模拟器的安装目录（只有输入中文时需要使用，大部分场景不需要配置该内容）
  ocr: False
Task: #配置执行任务,配置任务名称，如果需要传入参数在下面增加参数，可以根据不同的账号序号配置任务。
      #账号会执行小于等于并且离它最近的序号的任务列表
  1: #配置账号大于等于1的进行以下操作
     #最好每个任务结束后设置tohomepage，因为每个任务都是按照当前在首页的情况执行的
    # -
    #   - landsol_cup # 兰德索尔杯 随机选一个角色
    -
      - guild_like # 点赞行会成员
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
      - 6 # 绿龙
      - 1  #使用编号1队过小怪
      - '4' # 选择编组4过boss
      - '1,2,3,4,5,6,7,8,9,10' #使用上面选择的编组中编号1到10队过boss，小队之间用','分割使用''空串代表不打boss
      - False # 结束后是否退出地下城，在无法完成地下城时使用
    -
      - tohomepage
    -
      - quick_saodang # 使用快捷扫荡功能（游戏内置功能）
      - 2 # 使用预设2
    # -
    #   - tohomepage
    # -
    #   - activity_saodang  # 清活动图的日常(每次活动有区别，任务大概率无法执行)
    #   - True # 是否刷活动困难章节和高难boss
    #   - False # 是否将剩余体力花费在活动普通章节上
    # 扫荡露娜塔
    # -
    #   - tohomepage
    # -
    #   - luna_tower_saodang
    -
      - tohomepage
    -
      - shop_buy #商店购买
      -
        1: # 第一个tab（通常）购买前四个
          - 1
          - 2
          - 3
          - 4
        2: # 地下城
          - 1
        2_config: # 第二个栏的额外配置
          time: 3 # 执行3次，相当于重置2次
          buy_equip: True # 购买装备
          first_equip: 12 # 第一个装备位置
          end_equip: 19 # 最有一个装备的位置
          buy_threshold: 300 # 购买所有小于300的装备
          total_item_count: 20 # 当前tab下购买物品数量上限，用来计算是否是最后一行
        5: # 行会
          - 5
        8: # 限时，放到扫荡之后确保之前已经触发出来限时了
          - 1
          - 2
    -
      - tohomepage
    -
      - get_quest_reward  # 最后领下任务
    -
      - tohomepage
    -
      - get_gift # 领下礼物
```

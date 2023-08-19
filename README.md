## 介绍
> 该脚本为自用脚本，主要用于清日常。
> 因此有以下特点：
> 1. 脚本能运行的范围，只保证当前在用的功能可以执行（目前就是清日常），老的功能很可能就不能用了
> 2. 不存在稳定版本，所有的bug修复都在第二天跑脚本的时候验证。所以最新的提交并不一定解决了问题
> 3. 如果发现问题的话可以提ISSUE，有时间的话会进行修复（比如一些功能我现在不用所以也发现不了bug）

基于Open cv 模板匹配的脚本，模板图基于960x540的设备。对于其他分辨率识别效果不一定好(可能不能正常完成操作)。

## 已有能力

- [x] 清除所有未读剧情（包含主线、角色和公会，特别部分由于执行逻辑不一样这里不做处理）
- [x] 使用游戏内置扫荡工具（只是调用预设，需要预先设置好扫荡计划）
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
- [x] 领取公会小屋体力
- [x] 购买体力
- [x] 支持兰德索尔杯活动
- [x] 自动抽取免费十连功能
- [x] 购买1/10/20次mana功能
- [x] 领取任务奖励
- [x] 多设备登录及切换账号

## 使用引导

* 安装Python3环境，访问[Python官网](https://www.python.org/)安装
* 使用git clone或网页下载本项目到电脑上
* 执行以下命令安装项目所需依赖
  ```cmd
  pip install opencv_python matplotlib numpy pywin32 PyYAML
  ```
  如果在配置文件开启ocr功能，需要安装额外依赖，这里使用[easyocr](https://github.com/JaidedAI/EasyOCR)。
  注意：当第一次使用easyocr时会自动下载模型数据
  ```cmd
  pip install easyocr
  ```
* 在项目根目录创建`config.yml`文件，根据yaml语法配置账号信息及需要做的任务模块，具体可参考[sample_daily_config.yml](sample_daily_config.yml)这个文件
* 执行脚本之前，首先打开模拟器并打开游戏界面停留在欢迎页面
* 在当前目录cmd中执行以下命令启动脚本
  * 需要使用ADB命令，确保当前电脑ADB命令可用
    ```cmd
    python main.py
    ```
  * 或不使用ADB命令，但是需要配置好雷电模拟器路径
    ```cmd
    python main.py --mode 1
    ```
---
* 使用雷电模拟器多开注意模拟器标题不要改，并且要保证模拟器标题`雷电模拟器-1`这个后面的`-数字`要和多开器里显示的序号一致

## 直接执行指定任务

如果需要单独执行任务可以参考：[sample_run_single_task](sample_run_single_task.py)

## 配置信息参考

配置默认的账号及需要做哪些任务等信息，需要在工程目录下创建`config.yml`的文件，具体可参考根目录下[sample.yml](sample.yml)文件。如果是清日常的话，参考[sample_daily_config.yml](sample_daily_config.yml)文件，如果通过daily_task执行的话，则需要创建`daily_config.yml`文件。

另外如果使用[daily_task.py]（daily_task.py）执行每日任务的话，可以将活动限制的任务全部启用（示例文件中是默认注释掉的），该脚本会拉取当前正在进行的活动，只有对应活动时间段内才会执行活动限定任务。

```yaml
# 这个是用于清日常的配置文件
Accounts: #存账号信息
  -
    account: '账号1'
    password: '密码1'
  # - 
  #   account: '账号2'
  #   password: '密码2'
Extra:
  dnpath: 'G:\leidian\LDPlayer9' # 雷电模拟器路径，如果不使用ADB命令则必须配置这个路径
  ocr: True # 只有根据数量购买装备时需要，不需要这个功能可以设置为False
Task: #配置执行任务,配置任务名称，如果需要传入参数在下面增加参数，可以根据不同的账号序号配置任务。
      #账号序号就是Accounts中第几个账号，下述例子就是配置大于等于1的账号都执行下面的任务列表，如果在下面加入一个5：那么就是1-4执行1：后面的任务列表5以后执行5：后面的任务列表
  1: #最好每个任务结束后或前设置tohomepage，因为每个任务都是按照当前在首页的情况执行的，下面部分注释的任务是只有某些活动时可用，可以根据需要取消注释
    -
      - guild_like # 点赞行会成员
    # - 
    #   - tohomepage
    # -
    #   - choushilian #抽取免费十连
    #   - False #是否抽取所有免费十连，这里没判断是否是免费的十连，所以第二个参数最好不要传True，如果当前没有免费的十连的话就直接把钻石花光了
    -
      - tohomepage #回到首页
    -
      - normal_gacha #普通扭蛋10连
    -
      - tohomepage
    -
      - get_quest_reward #领取任务奖励
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
      - 7 # 极难4地下城, 极难3为6依次类推
      - 1  #使用编号1队过小怪
      - '4' # 选择编组4过boss
      - '1,2,3,4,5,6,7,8,9,10' #使用上面选择的编组中编号1到10队过boss，小队之间用','分割
                               #传入空串''则表示不打boss配合下方结束是否退出地下城使用
      - False # 结束后是否退出地下城，在无法完成地下城时使用
      - True # 如果能跳过是否执行跳过，默认True
    -
      - tohomepage
    -
      - quick_saodang
      - 2
    # -
    #   - tohomepage
    # -
    #   - activity_saodang  # 清活动图的日常
    #   - True # 是否刷活动困难章节和高难boss
    #   - True # 是否将剩余体力花费在活动普通章节上
    # -
    #   - tohomepage
    # -
    #   - luna_tower_saodang # 进行露娜塔的回廊扫荡，通过露娜塔后开放
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
        2_config: # 第二个栏的额外配置
          buy_equip: True # 购买装备
          first_equip: 1 # 第一个装备位置
          end_equip: 4 # 最后一个装备的位置
          buy_threshold: 300 # 购买所有小于300的装备
        3_config: 
          buy_equip: True 
          first_equip: 1 
          end_equip: 4 
          buy_threshold: 300 
        4_config: 
          buy_equip: True 
          first_equip: 1 
          end_equip: 4 
          buy_threshold: 300 
        8: #限定商店
         - -1 # 表示点击全选按钮即全部经验药水
    -
      - tohomepage
    -
      - get_quest_reward  # 领取任务奖励
    -
      - tohomepage
    -
      - get_gift # 领取礼物
      - True # 忽略体力收取
```

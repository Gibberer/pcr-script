# 新版剧情活动

`campaign_clean` 默认执行新版活动的重复日日常：困难扫荡、剧情/回忆录、活动任务和活动券兑换。首通与未通关首领暂时关闭，等待用户在新活动首日交付实测。困难关卡尚未全三星时报告 `deferred` 并跳过本轮活动任务；以游戏实际进度为准，不依赖旧日历的“第一天”。旧地图复刻尚未适配。跨会话接续见 [等待验证的场景](game-knowledge/pending-validation.md)。

## 安装与运行

在项目目录执行：

```powershell
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -r requirements-event.txt
./.venv/Scripts/python.exe -X utf8 scripts/agent/update_avatars.py --all
./.venv/Scripts/python.exe -X utf8 scripts/daily/story_event.py
```

`daily_config.yml` 中配置 `Extra.dnpath`。`scripts/daily/story_event.py` 操作已经打开并登录的雷电窗口，不启动其他日常，不调用 ADB，不移动系统鼠标或激活窗口。模拟器需保持可截图状态；普通 Windows 终端须与模拟器运行在同一桌面会话。建议使用 960×540 分辨率。

完整日常仍执行 `daily_task.py`。活动任务配置为：

```yaml
StoryEvent:
  teams: config/event_teams.yml
  first_clear: false # 等待新活动首日实测
  bosses: false # 等待未通关首领实战验证
  stories: true
  memoirs: true
  missions: true
  exchange: true
  max_boss_attempts: 10
  battle_timeout: 220
  timeout: 1800
Task:
  1:
    - [campaign_clean, true, false]
```

两个位置参数分别是“扫荡困难关卡”“将剩余体力用于普通关卡”。默认保留普通关卡体力。不购买体力，不重置困难次数，不自动强化角色或升级专武。活动任务在扫荡和剧情之后检查“每日、普通、特别、称号”四栏，随后兑换全部活动券。旧任务名 `clear_campaign_first_time` 和 `campaign_reward_exchange` 仍可使用；正常日常只需要 `campaign_clean`。

日常入口可用 `--only stories|memoirs|missions|sweep|exchange` 单独运行一项。Agent 另用 `scripts/agent/game.py` 保存截图和 OCR，增加 `--audit` 选择本期特别战斗＋模式 1 的第一套作业，读取培养信息并输出达标结果，不开始战斗。目录边界见 [入口分类](../scripts/README.md)。

## 头像与培养信息

旧 `_YoloDetector` 的类别就是角色 ID，新增未训练角色需要更新模型权重。旧 SIFT 检测逐人比对头像。新版活动使用独立的定位与身份索引：

1. 编队先用游戏内角色名搜索，缩小候选范围。
2. 检测头像卡片外框；一次矩阵运算查询全部候选的身份，设有相似度和候选差值门槛。
3. 长按打开国服角色详情，以基础名字、头像身份和该版本的两个普通技能名共同确认衣装，再读取当前等级、装备 Rank、星级、技能等级。详情弹窗本身不显示衣装后缀。
4. 等待头像轮播到专武信息帧，连续两次确认：无剑徽、单色剑徽、混色剑徽分别对应未开、仅专武 1、专武 1＋2。星数帧不会被当作“未开专武”。六星、专武 1、专武 2 三个开关均须与作业完全一致，任意开关未知或不一致都不进入战斗；不以技能变化替代专武直接标记，没有专武等级门槛。
5. 最后再次核对五名实际出战角色及顺序。

日服素材来自 [Estertion 的公开角色头像目录](https://redive.estertion.win/icon/unit/)，通过角色 ID 对应国服数据库中的完整名称。`scripts/agent/update_avatars.py --all` 预载日服角色，尚无国服名称的 ID 保留为 `unit:ID`；更新国服数据库后再次运行即可补齐名称，无需重训。默认不带 `--all` 时只更新作业引用角色。下载后日常离线使用 `cache/game/avatars/index.npz`，不逐张读取图片。游戏中确认过的新头像也可加入索引。图片、索引和账号截图均存放在已忽略的 `cache/` 下。

装备 Rank 与装备件数是不同的检查项：当前详情弹窗可读取 Rank，无法确认装备件数时记录为未知。作业若要求 `equipment: 6`，未知会判定不达标。头像相似、角色存在、Rank 足够均不直接等于整队通过检查。

## 首领作业与失败处理

`config/event_teams.yml` 按活动标题、难度和模式匹配，包含来源、五名角色要求、SET 设置及尝试次数。当前作业对应 “I Wish 后传 And I will” 的霸瞳皇帝，参考 [SP 作业](https://gamewith.jp/pricone-re/article/show/516586) 和 [SP＋作业](https://gamewith.jp/pricone-re/article/show/516593)，包含替换队。后续不同活动需要添加对应作业，未知首领不会套用旧队伍。

来源的专武等级、骑士强化、装备细节可能与本账号不同；仅检查专武开启不会保证来源的刀数。缺人、培养不达标或识别不确定时尝试备用队；无可用队则记录待处理并继续领奖。减员连续确认后从战斗菜单撤退；单场和整体均有限时、限次。SP 的结算和通关分开判断，回到首领页面后核实通关/模式，已通关首领每天跳过。不会点击首领详情中会重置整场进度的“放弃”。

作业中的 `null` 表示来源未明确某开关，会阻止该候选开战。本体怜替换项的专武 2 资料尚待补齐，不能把来源缺失默认成未开启；账号本体怜已开专武 2。主队无需此替换项。

## 输出与验证边界

`cache/daily/story_event/report.json` 保存日常步骤、战斗和未完成原因。Agent 审查另写 `cache/agent/story_event/audit.json`；对应运行目录的 `roster.json` 保存实际培养信息、观测时间和剑徽/角色截图路径。专武状态每次实时观察，不沿用旧缓存。异常会保留 `current.png/json`、错误或超时截图。出现未知消费确认时停止重复点击，数值识别失败不会视为零。

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s test -p test_event.py -v
```

离线用真实截图和 OCR 记录覆盖通关标记、星数、模式、扫荡二次确认、次数变化、缺失数字、作业隔离及禁止 ADB 回退。当前账号已经通关本期关卡和首领，因此未通关关卡推进、SP/SP＋实战通关属于推断实现，仍需下一期首次挑战时验证；不能把已通关场景的跳过检查算作首次通关验证。

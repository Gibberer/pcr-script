# 深域关卡推进

按需任务 `abyss_push`；GUI 入口为“按需专项 → 深域关卡”，命令行为：

```powershell
./.venv/Scripts/python.exe -X utf8 scripts/daily/task.py abyss_push
```

任务按火、水、风、光、暗的顺序定位地图 NEXT，读取关卡详情，获取适用来源并核对当前账号的角色身份和培养。完整来源要求不明时不会把账号现状当成攻略要求。本地试打需要显式开启 `Abyss.allow_local_trials`（默认关闭）；试打队伍和有来源的队伍会分别标记。

```yaml
Abyss:
  search_effort: normal
  source_urls: []
  allow_local_trials: false
  max_failures_per_stage: 6
  max_repeat_failures_per_stage: 2
  max_battles: 30
  allow_five_star_upgrade: false
  allow_divine_amulets: false
  auto_collect_house_stamina: false
  sources:
    max_video_seconds: 180
    max_download_seconds: 180
```

可在 `source_urls` 填写本任务优先攻略链接；为空时会自动搜索。优先链接也占用 `sources.max_videos` 名额；跨属性、跨章节推进时，若只允许解析一个视频，旧攻略可能挤掉当前关卡搜索结果。公共头像索引和已支持的视频布局由程序准备和解析，但目前不能从任意视频可靠还原完整作业。可设置 `prepare_only: true` 只获取并解析，不操作游戏；详细适用范围见[视频解析](../video-strategies.md)。

`search_effort: high` 适合卡在失败关时使用。它把搜索扩至自动作业、配队、通关阵容和一图流等措辞；默认核对至多 96 条候选详情，解析预算提高到 12 个视频、每视频 8 个分 P、每分 P 96 帧。单分 P 时长、下载和解析时间边界分别提高到 600、420 和 3600 秒。已有 `sources` 数值若更高则保留。高档在本关失败预算已耗尽时仍搜索并报告新来源，但不会因此增加战斗预算或开战；多个关卡连续搜索时还受 `Abyss.timeout` 限制。默认 `normal` 沿用较小的搜索与解析范围。

高档也直接搜索关卡名、“关卡名 全 set”及“最新自动”作业。候选详情核验先看明确关卡，再优先发布时间较近的视频，同发布时间再看自动操作提示，使新角色阵容更早进入解析。单视频标题即使分 P 只有通用名称，也参与精确关卡排序。标题若明确对应当前属性关卡并写明“全 SET”，可作为五人 SET 开关证据；若标题含手动操作、TP+2 等未核实要求，或视频帧给出相反开关，则拒绝该声明。账号本地试打还需明确的 AUTO 开启证据。

目标分 P 较长时，可分别提高 `sources.max_video_seconds`（允许解析的片长）和 `sources.max_download_seconds`（单个视频的下载时间上限，最多 900 秒），并让 `sources.parse_timeout` 覆盖下载与解析总耗时。延长时间只让解析器尝试取得画面，不会放宽关卡、身份、手动操作或培养条件的核验。

允许本地试打时，会先核对五名角色，再按失败记录有限重试或换队；有依据的替补属于本地试验，不冒充来源推荐。战前可用游戏的“自动装备”调整特别装备，它可能从其他角色取现有装备，不进行强化或分解。五星升级和女神秘石兑换是两个独立的消费开关，默认都关闭；不购买体力、重置次数、升六星或投入专武资源。

启用 `auto_collect_house_stamina: true` 后，只有在挑战弹出「体力不足」并已取消回复提示时，任务才会尝试前往公会之家「全部收取」一次。程序要求领取回执包含体力且顶栏数值增加，随后重新读取关卡和剩余挑战次数；无法核实时停止。该选项默认关闭，领取的是已生产的家具产物，不购买体力。

同一关的失败预算会读取账号本地试打历史，重启任务不重置 `max_failures_per_stage`；未能确认战后进度的中断战斗也占用安全预算。达到上限后跳过该属性，继续检查后续属性。

以战后同属性 NEXT 前进确认过关。次数用尽、体力不足、无可用队伍、身份/专武不明或未知页面会在运行记录中给出原因；无 NEXT 不直接等于全部通关。记录位于 `cache/daily/runs/`；地图和养成页面的游戏知识见[深域](../game-knowledge/abyss.md)。

# Agent 文档索引

根目录 [README](../README.md) 只引导使用；面向人的说明集中在 [guides/](guides/desktop.md)。本索引用于定位工程和游戏知识的唯一维护页。按问题只读对应专题与测试，不通读目录。

| 问题 | 主文档 |
|---|---|
| 图形界面安装与设备连接 | [GUI 指南](guides/desktop.md) |
| 命令行安装与运行 | [命令行指南](guides/command-line.md) |
| 任务如何使用与消费范围 | [任务指南](guides/tasks.md) |
| 代码职责与任务注册 | [项目结构](project-structure.md)、[任务架构](task-architecture.md) |
| 运行异常、设备接管与沙箱下截图失败 | [运行诊断](run-diagnostics.md) |
| 视频来源、头像与解析边界 | [视频解析](video-strategies.md) |
| 共用配队、角色数据库、培养差距与战前装备 | [公共准备流程](party-preparation.md)、[游戏配队知识](game-knowledge/party-building.md) |
| 地下城、深域等玩法的执行实现 | [任务指南](guides/tasks.md)及其专项链接 |
| 黎明界迷宫通行证消费与任务奖励 | [使用指南](guides/dawn-labyrinth.md)、[游戏页面与规则](game-knowledge/dawn-labyrinth.md) |
| 追忆战场首通、报酬与霸日常扫荡 | [使用指南](guides/recollection.md)、[游戏页面与规则](game-knowledge/recollection.md) |
| 深渊讨伐战开放期、前哨与首领日常 | [使用指南](guides/abyss-subjugation.md)、[游戏页面与规则](game-knowledge/abyss-subjugation.md) |
| 游戏中的页面、角色与机制 | [游戏知识](game-knowledge/README.md) |
| 公会之家体力的游戏入口与回执 | [公会之家](game-knowledge/guild-house.md) |
| 尚需真实环境的工程验收 | [工程待办](pending-validation.md) |
| GUI 构建与发布 | [发布](releases.md) |

文档规则：

- guides/：供人使用的安装、操作和任务说明；截图与示例配置也在该目录。
- game-knowledge/：只写游戏页面关系、可观察状态和机制；不写代码、测试、运行编号、开发经过或任务授权。按专题写当前结论、适用服区/版本及验证状态。自然出现才可核实的游戏状态放其 pending-validation.md。
- 其他 docs/ 页面：Agent 使用的架构、实现边界、诊断与发布知识。未完成工程事项只记在本目录 pending-validation.md：写事项与验收条件，完成后删除，不保留完成记录。
- 未完成工作的临时分析放忽略的 cache/agent/work-notes/<task>/；完成后清除。可复用结论归入唯一专题，原始截图、运行日志和构建产物留在忽略目录，不写流水账。

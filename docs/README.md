# Agent 文档索引

根目录 [README](../README.md) 只引导使用；面向人的说明集中在 [guides/](guides/desktop.md)。本索引用于定位工程和游戏知识的唯一维护页。

| 问题 | 主文档 |
|---|---|
| GUI 与任务如何使用 | [GUI 指南](guides/desktop.md)、[任务指南](guides/tasks.md) |
| 代码职责与任务注册 | [项目结构](project-structure.md)、[任务架构](task-architecture.md) |
| 运行异常与控制 | [运行诊断](run-diagnostics.md) |
| 视频来源、头像与解析边界 | [视频解析](video-strategies.md) |
| 地下城、深域等玩法的执行实现 | [任务指南](guides/tasks.md)及其专项链接 |
| 游戏中的页面、角色与机制 | [游戏知识](game-knowledge/README.md) |
| 尚需真实环境的工程验收 | [工程待办](pending-validation.md) |
| GUI 构建与发布 | [发布](releases.md) |

文档规则：

- guides/：供人使用的安装、操作和任务说明；截图与示例配置也在该目录。
- game-knowledge/：只写游戏页面关系、可观察状态和机制；不写代码、测试、运行编号、开发经过或任务授权。按专题写当前结论、适用服区/版本及验证状态。自然出现才可核实的游戏状态放其 pending-validation.md。
- 其他 docs/ 页面：Agent 使用的架构、实现边界、诊断与发布知识。真实环境尚待验收的实现放本目录 pending-validation.md。
- 未完成工作的临时分析放忽略的 cache/agent/work-notes/<task>/；完成后清除。可复用结论归入唯一专题，原始截图、运行日志和构建产物留在忽略目录，不写流水账。

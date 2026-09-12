# 入口分类

| 路径 | 用途 | 可以放入定时任务 |
|---|---|---|
| 根目录 `daily_task.py` | 现有完整日常，读取 `daily_config.yml` | 是 |
| `scripts/daily/all.bat` | 完整日常定时入口，自动设置工作目录和本地 Python，无暂停 | 是 |
| `scripts/daily/story_event.py` | 单独执行固化的剧情活动日常 | 是 |
| `scripts/daily/story_event.bat` | 单独活动的 Windows 定时入口，无暂停 | 是 |
| `scripts/agent/game.py` | 截图、OCR、后台点击/输入、配队审查 | 否 |
| `scripts/agent/update_avatars.py` | 维护日服头像索引 | 否，按需更新 |
| `scripts/_game.py` | 共用启动配置，无任务动作 | 不是运行入口 |

共享界面能力在 `pcrscript/game_ui/`；活动流程在 `pcrscript/daily/`；作业在 `config/`；Agent 知识在 `docs/game-knowledge/`。

```powershell
# 日常；也可继续运行原来的 daily_task.py
./.venv/Scripts/python.exe -X utf8 scripts/daily/story_event.py
# Agent 观察与核验
./.venv/Scripts/python.exe -X utf8 scripts/agent/game.py
./.venv/Scripts/python.exe -X utf8 scripts/agent/game.py --audit
./.venv/Scripts/python.exe -X utf8 scripts/agent/update_avatars.py --all
```

日常结果写入 `cache/daily/`，Agent 观察写入 `cache/agent/`，共用头像索引写入 `cache/game/avatars/`。早期开发截图仍在 `cache/story_event/`，仅作历史证据。

# GUI 构建与发布

主分支为 `master`。GUI 源码、GUI Python 接口或 GUI 烟测脚本变更时，PR 和分支提交执行 Windows GUI 构建并上传 Artifact；其他 Python、任务、依赖和默认配置变更只运行 Python 回归。发布仅由 `gui-v*` 标签触发，标签提交必须已经包含在 `origin/master` 中；标签发布始终重新构建 GUI。

## 本地验证

```powershell
./.venv/Scripts/python.exe -X utf8 -m unittest discover -s test -p 'test_*.py'
dotnet build desktop/PcrDesktop/PcrDesktop.csproj -c Release -o artifacts/gui -p:DebugType=None -p:DebugSymbols=false
./test/verify_desktop_runtime.ps1 -Python ./.venv/Scripts/python.exe
```

构建使用 .NET 10 SDK，输出面向系统 .NET Framework 4.8 的 x64 GUI，不捆绑 .NET 10 运行时。验证脚本使用合成配置、下载到临时目录、离屏渲染页面，并测试辅助进程超时终止；本地另用真实 WPF 窗口复核日常列表与添加对话框。不操作模拟器。截图不能代替真实游戏验收。

## 合并后发布

1. 确认 PR 已审核、合并进 `master`，并确认 Windows GUI 检查通过。
2. 在要发布的已合并提交上创建一个新的 `gui-v<版本号>` 标签并推送。不要复用或移动旧发布标签。
3. `Windows GUI` 工作流先执行 Python 回归、GUI 编译、核心/完整下载验证、离屏界面验证与 5 MB 体积检查，生成 ZIP 和 SHA-256。
4. 发布 job 下载这一次构建的 Artifact，确认标签提交属于 `master`、核对 SHA-256，再创建 GitHub Release，附上 `PcrDesktop-win-x64.zip` 与 `SHA256SUMS.txt`。同名 Release 已存在则停止，不覆盖已发布文件。
5. 从 Release 页面重新下载文件，核对 SHA-256，在干净 Windows 环境验证解压、首次引导、工程下载及依赖安装。正常日常中的游戏操作验收沿用知识库待办，不为打包而重复消费。

手动 `workflow_dispatch` 只构建，不发布。写权限只授予标签发布 job；普通构建只读。实现见 `.github/workflows/desktop.yml`，命令依据 [gh release create](https://cli.github.com/manual/gh_release_create) 和 [GITHUB_TOKEN 权限](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token)。

## 交付内容

用户下载可直接启动的 GUI ZIP，必须一起保留 EXE、DLL、`.exe.config`。GUI 内部下载 Python 源码和图片；默认只取核心运行目录，不要求用户提前 clone 整个仓库。默认源码分支为 `master`。旧版的默认开发分支设置自动迁移到 `master`，用户明确设置的其他分支仍保留，可在环境设置中自行切换。

不打包账号、实际配置、游戏数据库、头像、视频、作业或运行证据。源码更新为显式快进更新，GUI EXE 更新仍通过下载新 Release 包完成。暂未提供自动回滚或版本隔离的 Python 依赖环境。

本地构建通过不代表已在 GitHub 发布；以标签工作流的发布结果与 Release 附件为准。

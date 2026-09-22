using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;
using Microsoft.Win32;

namespace PcrDesktop;

public partial class MainWindow : Window
{
    private readonly ObservableCollection<TaskRow> _plan = [];
    private readonly List<(JsonObject Descriptor, FrameworkElement Editor)> _parameters = [];
    private readonly List<(JsonObject Descriptor, FrameworkElement Editor)> _specialParameters = [];
    private readonly DispatcherTimer _timer = new() { Interval = TimeSpan.FromSeconds(1) };
    private readonly JsonSerializerOptions _pretty = StatusDisplay.ReadableJson;
    private Settings _settings = new();
    private Settings? _loadedSettings;
    private Settings? _runSettings;
    private string _revision = "";
    private string? _runId;
    private string? _pendingCommand;
    private string? _pendingAction;
    private DateTimeOffset _requestedAt;
    private DateTimeOffset _startedAt;
    private Process? _process;
    private bool _busy;
    private bool _active;
    private bool _environmentReady = true;
    private bool _newConfig;

    public MainWindow() : this(true) { }

    public MainWindow(bool loadSettings)
    {
        if (loadSettings) _settings = Settings.Load();
        InitializeComponent();
        WorkspaceBox.Text = _settings.Workspace;
        PythonBox.Text = _settings.Python;
        ConfigBox.Text = _settings.Config;
        BootstrapBox.Text = _settings.BootstrapPython;
        RepositoryBox.Text = _settings.Repository;
        BranchBox.Text = _settings.Branch;
        DownloadScopeBox.SelectedIndex = _settings.DownloadCoreOnly ? 0 : 1;
        EmulatorLabel.Text = "雷电目录：" + _settings.EmulatorDirectory;
        PlanGrid.ItemsSource = _plan;
        _plan.CollectionChanged += (_, _) => UpdatePlanLabels();
        RefreshConfigChoices();
        _timer.Tick += (_, _) => Poll();
        _timer.Start();
        if (loadSettings) Loaded += async (_, _) => await Guard(async () =>
        {
            if (Directory.Exists(WorkspaceBox.Text) && !string.IsNullOrWhiteSpace(PythonBox.Text))
            {
                await LoadPreferredConfig();
            }
        });
    }

    private void Message(string text) => MessageText.Text = text;
    private void Log(string text) => Dispatcher.Invoke(() =>
    {
        // Bound UI memory while the complete log remains in the run directory.
        if (LiveLog.Text.Length > 180_000) LiveLog.Text = LiveLog.Text.Substring(LiveLog.Text.Length - 120_000);
        LiveLog.AppendText(text + Environment.NewLine);
        LiveLog.ScrollToEnd();
    });

    private async Task Guard(Func<Task> action)
    {
        if (_busy) { Message("正在处理上一项操作，请稍候"); return; }
        _busy = true;
        try { await action(); }
        catch (Exception error) { Message(error.Message); Log(error.Message); }
        finally { _busy = false; }
    }

    private Settings ReadSettings()
    {
        var workspace = Path.GetFullPath(WorkspaceBox.Text.Trim());
        if (!Directory.Exists(workspace)) throw new IOException("请选择已存在的工程目录");
        return new Settings
        {
            Workspace = workspace, Python = PythonBox.Text.Trim(), Config = ConfigBox.Text.Trim(),
            BootstrapPython = BootstrapBox.Text.Trim(), Repository = RepositoryBox.Text.Trim(), Branch = BranchBox.Text.Trim(),
            RecentConfigs = [.. _settings.RecentConfigs],
            EmulatorDirectory = _settings.EmulatorDirectory, SetupCompleted = _settings.SetupCompleted,
            DownloadCoreOnly = DownloadScopeBox.SelectedIndex == 0
        };
    }

    private void RequireLoaded(bool ignoreConfigPath = false)
    {
        if (_loadedSettings is null) throw new InvalidOperationException("请先加载配置");
        var current = ReadSettings();
        if (current.Workspace != _loadedSettings.Workspace || (!ignoreConfigPath && current.Config != _loadedSettings.Config) || current.Python != _loadedSettings.Python)
            throw new InvalidOperationException("环境设置已变化，请重新加载配置");
    }

    private async Task Idle(Settings settings)
    {
        if (_active || _process is { HasExited: false }) throw new InvalidOperationException("请先停止当前任务并等待确认");
        await Backend.Request(settings, "idle");
    }

    private async Task LoadConfig(bool saveSettings = true)
    {
        var settings = ReadSettings();
        var data = await Backend.Request(settings, "load");
        _defaultOptions = (await Backend.Request(settings, "new"))["options"]!.AsObject();
        _settings = settings;
        if (saveSettings) _settings.Save();
        _loadedSettings = settings;
        _newConfig = false;
        _revision = data["revision"]!.GetValue<string>();
        _plan.Clear();
        foreach (var item in data["plan"]!.AsArray())
            _plan.Add(new TaskRow { Enabled = item!["enabled"]!.GetValue<bool>(), Name = item["name"]!.GetValue<string>(), Args = item["args"]!.ToJsonString() });
        SetCatalog(data["catalog"]!.AsArray());
        OptionsBox.Text = data["options"]!.ToJsonString(_pretty);
        BuildOptions(data["options"]!.AsObject());
        EnvironmentLabel.Text = Path.GetFileName(settings.Workspace);
        Message($"已加载配置 · 任务组 {data["account_group"]} · {_plan.Count} 项");
        CurrentConfigText.Text = "当前配置：" + settings.Config;
        if (saveSettings) RememberConfig(settings);
        else RefreshConfigChoices();
        // Reattach to a run started by this GUI before it was closed.
        if (!_active && saveSettings)
        {
            var root = Path.Combine(settings.Workspace, "cache", "daily", "runs");
            if (Directory.Exists(root))
                foreach (var folder in Directory.GetDirectories(root).OrderByDescending(path => path))
                {
                    if (!Guid.TryParse(Path.GetFileName(folder), out _)) continue;
                    try
                    {
                        var state = Backend.ReadObject(Path.Combine(folder, "status.json"));
                        if (state["state"]?.ToString() is "running" or "paused")
                        {
                            _runId = Path.GetFileName(folder); _runSettings = settings; _active = true;
                            _startedAt = Directory.GetCreationTimeUtc(folder);
                            Poll(); break;
                        }
                    }
                    catch (IOException) { }
                }
        }
    }

    private async Task SaveConfig()
    {
        RequireLoaded();
        if (_newConfig) { await SaveAs(); return; }
        await Idle(_loadedSettings!);
        var result = await Backend.Request(_loadedSettings!, "save", ConfigRequest());
        _revision = result["revision"]!.GetValue<string>();
        Message("配置已保存");
    }

    private JsonObject ConfigRequest()
    {
        PlanGrid.CommitEdit(DataGridEditingUnit.Cell, true);
        PlanGrid.CommitEdit(DataGridEditingUnit.Row, true);
        var plan = new JsonArray();
        foreach (var row in _plan)
            plan.Add(new JsonObject { ["enabled"] = row.Enabled, ["name"] = row.Name, ["args"] = JsonNode.Parse(row.Args)!.AsArray() });
        var options = ReadOptions();
        OptionsBox.Text = options.ToJsonString(_pretty);
        return new JsonObject { ["revision"] = _revision, ["plan"] = plan, ["options"] = options };
    }

    private void BuildParameters(JsonArray? values = null)
    {
        if (TaskPicker.SelectedItem is not TaskChoice task) return;
        TaskDescription.Text = task.Description;
        FillParameters(task, ParameterPanel, _parameters, values);
    }

    private void FillParameters(TaskChoice task, StackPanel panel,
        List<(JsonObject Descriptor, FrameworkElement Editor)> editors, JsonArray? values = null)
    {
        panel.Children.Clear(); editors.Clear();
        int index = 0;
        foreach (var node in task.Parameters)
        {
            var descriptor = node!.AsObject();
            var value = values is not null && index < values.Count ? values[index] : descriptor["default"];
            panel.Children.Add(new TextBlock { Text = (descriptor["label"] ?? descriptor["name"])!.ToString() + (descriptor["required"]!.GetValue<bool>() ? " *" : "") });
            FrameworkElement editor = descriptor["type"]!.ToString() == "boolean"
                ? new CheckBox { IsChecked = value?.GetValue<bool>() ?? false, Margin = new Thickness(0, 8, 0, 14) }
                : new TextBox { Text = descriptor["type"]!.ToString() == "string" ? value?.GetValue<string>() ?? "" : value?.ToJsonString() ?? "null" };
            panel.Children.Add(editor); editors.Add((descriptor, editor)); index++;
        }
    }

    private JsonArray ParameterValues(List<(JsonObject Descriptor, FrameworkElement Editor)>? editors = null)
    {
        var result = new JsonArray();
        foreach (var (descriptor, editor) in editors ?? _parameters)
        {
            if (editor is CheckBox check) result.Add(check.IsChecked == true);
            else
            {
                var text = ((TextBox)editor).Text;
                result.Add(descriptor["type"]!.ToString() == "string" ? JsonValue.Create(text) : JsonNode.Parse(text));
            }
        }
        return result;
    }

    private async Task StartRun(bool daily, bool special = false)
    {
        if (special && CatalogList.SelectedItem is not TaskChoice) throw new InvalidOperationException("请选择专项任务");
        if (!daily && _loadedSettings is null)
        {
            var selected = ((special ? CatalogList.SelectedItem : TaskPicker.SelectedItem) as TaskChoice)?.Name ?? throw new InvalidOperationException("请选择任务");
            var values = ParameterValues(special ? _specialParameters : _parameters);
            await CreateNewConfig();
            if (special)
            {
                CatalogList.SelectedItem = CatalogList.Items.Cast<TaskChoice>().Single(t => t.Name == selected);
                FillParameters((TaskChoice)CatalogList.SelectedItem, SpecialParameterPanel, _specialParameters, values);
            }
            else { TaskPicker.SelectedItem = TaskPicker.Items.Cast<TaskChoice>().Single(t => t.Name == selected); BuildParameters(values); }
        }
        RequireLoaded(ignoreConfigPath: !daily);
        await PythonEnvironment.RequireReady(ReadSettings());
        if (!_environmentReady) throw new InvalidOperationException("源码已更新，请先成功安装依赖");
        await Idle(_loadedSettings!);
        if (daily)
        {
            await SaveConfig();
            if (_newConfig) return; // Cancelling a batch save must not start it.
        }
        string task = daily ? "daily" : ((special ? CatalogList.SelectedItem : TaskPicker.SelectedItem) as TaskChoice)?.Name ?? throw new InvalidOperationException("请选择任务");
        var args = daily ? new JsonArray() : ParameterValues(special ? _specialParameters : _parameters);
        var request = new JsonObject { ["task"] = task, ["args"] = args };
        if (!daily)
        {
            var options = special ? ReadSpecialOptions() : ReadOptions();
            if ((_choices.FirstOrDefault(t => t.Name == task)?.RequiresDevice ?? true) && string.IsNullOrWhiteSpace(options["Extra"]?["dnpath"]?.ToString()))
                throw new InvalidOperationException("请先在配置选项页填写雷电安装目录；单任务无需保存配置文件");
            request["options"] = options;
        }
        _runSettings = _loadedSettings;
        _runId = Guid.NewGuid().ToString();
        _pendingCommand = null; _pendingAction = null;
        _startedAt = DateTimeOffset.Now;
        _active = true;
        RunScopeText.Text = daily ? "每日日常 · " + Path.GetFileName(_loadedSettings!.Config) : (special ? "按需专项 · " : "单项日常 · ") + (_choices.FirstOrDefault(t => t.Name == task)?.Label ?? task);
        LiveLog.Clear(); Tabs.SelectedItem = RunTab;
        try
        {
            var command = new List<string> { "-X", "utf8", "-u", "pcrscript/desktop.py", "run", "--run-id", _runId };
            if (daily) command.AddRange(["--config", _runSettings!.Config]);
            _process = Backend.Start(_runSettings!.Python, command, _runSettings.Workspace);
            var process = _process;
            await Backend.WriteInput(process, request.ToJsonString());
            _ = Observe(process);
            Message("已启动 Python，等待运行状态");
        }
        catch { _active = false; throw; }
    }

    private async Task Observe(Process process)
    {
        async Task Drain(StreamReader reader)
        {
            while (await reader.ReadLineAsync() is { } line) Log(line);
        }
        try
        {
            await Task.WhenAll(Drain(process.StandardOutput), Drain(process.StandardError), process.WaitForExitAsync());
            Poll();
            Message($"Python 进程已退出，退出码 {process.ExitCode}");
            if (_active) StatusText.Text += $"\n进程已退出（{process.ExitCode}）；若状态未正常结束，请查看日志。";
        }
        catch (Exception error) { Message(error.Message); }
        finally { _active = false; _process = null; process.Dispose(); }
    }

    private string? CurrentRunPath => _runSettings is null || _runId is null ? null : Path.Combine(_runSettings.Workspace, "cache", "daily", "runs", _runId);

    private void Poll()
    {
        var folder = CurrentRunPath;
        if (folder is null) return;
        try
        {
            var state = Backend.ReadObject(Path.Combine(folder, "status.json"));
            string value = state["state"]!.ToString();
            var age = DateTimeOffset.Now.ToUnixTimeSeconds() - state["heartbeat"]!.GetValue<double>();
            var label = value switch { "running" => "运行中", "paused" => "已暂停", "finished" => "已结束", "failed" => "失败", "cancelled" => "已停止", _ => value };
            if (age > 10 && value is "running" or "paused") label = "心跳失联（不能视为已停止）";
            if (_pendingCommand is not null)
            {
                var ack = state[_pendingAction == "snapshot" ? "snapshot_id" : "command_id"]?.ToString();
                if (ack == _pendingCommand) { _pendingCommand = null; Message("控制请求已确认"); }
                else label += $" · 等待{_pendingAction}确认" + (DateTimeOffset.Now - _requestedAt > TimeSpan.FromSeconds(10) ? "（已超时，尚未确认）" : "");
            }
            StatusText.Text = $"{state["name"]} · {label} · 耗时 {(DateTimeOffset.Now - _startedAt):hh\\:mm\\:ss}\n错误数：{state["errors"]}   最近操作：{StatusDisplay.Format(state["last_operation"])}\n当前步骤：{StatusDisplay.FormatStep(state["current_step"])}";
            if (value is "finished" or "failed" or "cancelled") _active = false;
        }
        catch (FileNotFoundException) { if (_active) StatusText.Text = "正在启动，等待 Python 创建运行记录…"; }
        catch (Exception e) when (e is IOException or JsonException) { Message("读取运行状态暂不可用：" + e.Message); }
    }

    private async Task SendControl(string action)
    {
        if (!_active || _runSettings is null || _runId is null) throw new InvalidOperationException("没有活跃运行");
        if (_pendingCommand is not null && action != "stop") throw new InvalidOperationException("上一个控制请求尚未确认");
        var response = await Backend.Request(_runSettings, "control", null, "--run-id", _runId, "--action", action);
        _pendingCommand = response["command_id"]!.ToString(); _pendingAction = action; _requestedAt = DateTimeOffset.Now;
        Poll();
    }

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        if (_busy || _active)
        {
            e.Cancel = true;
            Message("请先等待当前操作结束；运行中的任务须停止并确认后再关闭窗口。");
        }
        else _timer.Stop();
    }

    private async void Load_Click(object sender, RoutedEventArgs e) => await Guard(() => LoadConfig());
    private async void Save_Click(object sender, RoutedEventArgs e) => await Guard(SaveConfig);
    private async void Daily_Click(object sender, RoutedEventArgs e) => await Guard(() => StartRun(true));
    private async void Single_Click(object sender, RoutedEventArgs e) => await Guard(() => StartRun(false, special: true));
    private async void DailySingle_Click(object sender, RoutedEventArgs e) => await Guard(() => StartRun(false));
    private async void Pause_Click(object sender, RoutedEventArgs e) => await Guard(() => SendControl("pause"));
    private async void Resume_Click(object sender, RoutedEventArgs e) => await Guard(() => SendControl("resume"));
    private async void Stop_Click(object sender, RoutedEventArgs e) => await Guard(() => SendControl("stop"));
    private async void Snapshot_Click(object sender, RoutedEventArgs e) => await Guard(() => SendControl("snapshot"));
    private async void RefreshRun_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        Poll();
        if (_runSettings is null) return;
        await Backend.Request(_runSettings, "idle");
        _active = false;
        _pendingCommand = null;
        StatusText.Text += "\n已检查运行锁：当前工程无活跃任务进程。";
        Message("运行锁已释放，可以重新启动任务或关闭窗口");
    });
    private void Task_SelectionChanged(object sender, SelectionChangedEventArgs e) => BuildParameters();
    private void Plan_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (PlanGrid.SelectedItem is not TaskRow row) return;
        TaskPicker.SelectedItem = TaskPicker.Items.Cast<TaskChoice>().FirstOrDefault(t => t.Name == row.Name);
        BuildParameters(JsonNode.Parse(row.Args)!.AsArray());
    }
    private async void Add_Click(object sender, RoutedEventArgs e) => await Guard(() =>
    {
        if (TaskPicker.SelectedItem is TaskChoice task)
        {
            if (task.Category != "daily") throw new InvalidOperationException("专项请在按需专项页执行，不自动加入日常");
            _plan.Add(new TaskRow { Name = task.Name, Args = ParameterValues().ToJsonString() });
        }
        return Task.CompletedTask;
    });
    private async void Apply_Click(object sender, RoutedEventArgs e) => await Guard(() =>
    {
        if (PlanGrid.SelectedItem is TaskRow row && TaskPicker.SelectedItem is TaskChoice task)
        {
            row.Name = task.Name; row.Args = ParameterValues().ToJsonString(); UpdatePlanLabels();
        }
        return Task.CompletedTask;
    });
    private void Up_Click(object sender, RoutedEventArgs e) { var i = PlanGrid.SelectedIndex; if (i > 0) _plan.Move(i, i - 1); }
    private void Down_Click(object sender, RoutedEventArgs e) { var i = PlanGrid.SelectedIndex; if (i >= 0 && i < _plan.Count - 1) _plan.Move(i, i + 1); }
    private void Remove_Click(object sender, RoutedEventArgs e) { if (PlanGrid.SelectedItem is TaskRow row) _plan.Remove(row); }
    private void Browse_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "选择 Python 工程目录" };
        if (dialog.ShowDialog(this) == true)
        {
            WorkspaceBox.Text = dialog.FolderName;
            PythonBox.Text = Path.Combine(dialog.FolderName, ".venv", "Scripts", "python.exe");
        }
    }
    private async void Settings_Click(object sender, RoutedEventArgs e) => await Guard(() => { _settings = ReadSettings(); _settings.Save(); Message("环境设置已保存"); return Task.CompletedTask; });

    private void PythonDownload_Click(object sender, RoutedEventArgs e) => PythonEnvironment.OpenDownload();
    private async void DetectPython_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        BootstrapBox.Text = await PythonEnvironment.Detect(BootstrapBox.Text.Trim(), ReadSettings().Workspace);
        Message("已检测到 Python：" + BootstrapBox.Text + "。现在可创建环境 / 安装依赖。");
    });

    private async void Install_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var settings = ReadSettings();
        if (_active) throw new InvalidOperationException("请先停止任务");
        if (File.Exists(settings.Python)) await Idle(settings);
        _environmentReady = false;
        PythonBox.Text = await PythonEnvironment.Install(settings.Workspace, settings.BootstrapPython, Log);
        await LoadPreferredConfig();
        _environmentReady = true;
        Message("Python 环境已就绪");
    });

    private async void Clone_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (_active) throw new InvalidOperationException("请先停止任务");
        var dialog = new OpenFolderDialog { Title = "选择下载位置（将在其中新建 pcr-script 文件夹）" };
        if (dialog.ShowDialog(this) != true) return;
        var target = Path.Combine(dialog.FolderName, "pcr-script");
        if (Directory.Exists(target)) throw new IOException("目标文件夹已存在，请选择其他位置或直接打开现有工程");
        await RuntimeSource.Download(RepositoryBox.Text.Trim(), BranchBox.Text.Trim(), target, Log, coreOnly: DownloadScopeBox.SelectedIndex == 0);
        WorkspaceBox.Text = target; PythonBox.Text = Path.Combine(target, ".venv", "Scripts", "python.exe");
        _settings = ReadSettings(); _settings.Save(); _loadedSettings = null;
        Message("源码下载完成，请创建 Python 环境 / 安装依赖");
    });

    private async Task<string> Git(Settings settings, params string[] args) => (await Backend.Command("git", args, settings.Workspace)).Trim();
    private async void Version_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var settings = ReadSettings();
        Message("本地版本：" + await Git(settings, "log", "-1", "--format=%h %s"));
    });
    private async void Update_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var settings = ReadSettings(); await Idle(settings);
        if ((await Git(settings, "status", "--porcelain")).Length > 0) throw new IOException("存在本地源码改动，更新已取消；请先处理改动");
        if (await Git(settings, "branch", "--show-current") != settings.Branch) throw new IOException("当前分支与设置不一致，更新已取消");
        await Backend.Command("git", ["fetch", "origin", settings.Branch], settings.Workspace, log: Log, timeoutSeconds: 600);
        await Idle(settings);
        await Git(settings, "merge", "--ff-only", "FETCH_HEAD");
        _environmentReady = false;
        Message("源码已更新。请安装依赖后重新加载配置再运行。");
    });

    private void OpenFolder(string? path)
    {
        if (path is not null && Directory.Exists(path)) Process.Start(new ProcessStartInfo("explorer.exe") { Arguments = WindowsCompatibility.QuoteArgument(path), UseShellExecute = false });
    }
    private void OpenRun_Click(object sender, RoutedEventArgs e) => OpenFolder(CurrentRunPath);
    private void OpenHistory_Click(object sender, RoutedEventArgs e) => OpenFolder((HistoryList.SelectedItem as RunChoice)?.Path);
    private async void History_Click(object sender, RoutedEventArgs e) => await Guard(() =>
    {
        var root = Path.Combine(ReadSettings().Workspace, "cache", "daily", "runs");
        var rows = new List<RunChoice>();
        if (Directory.Exists(root))
            foreach (var path in Directory.GetDirectories(root).OrderByDescending(Directory.GetCreationTimeUtc).Take(100))
            {
                try
                {
                    var state = Backend.ReadObject(Path.Combine(path, "status.json"));
                    rows.Add(new RunChoice(path, $"{Directory.GetCreationTime(path):MM-dd HH:mm} · {state["name"]} · {state["state"]}"));
                }
                catch (Exception error) when (error is IOException or JsonException) { }
            }
        HistoryList.ItemsSource = rows;
        return Task.CompletedTask;
    });
    private async void History_SelectionChanged(object sender, SelectionChangedEventArgs e) => await Guard(async () =>
    {
        if (HistoryList.SelectedItem is not RunChoice item) return;
        var state = Backend.ReadObject(Path.Combine(item.Path, "status.json"));
        var text = state.ToJsonString(_pretty);
        var tasks = Path.Combine(item.Path, "tasks");
        if (Directory.Exists(tasks))
            foreach (var file in Directory.GetFiles(tasks, "result.json", SearchOption.AllDirectories)) text += "\n\n" + await Task.Run(() => File.ReadAllText(file));
        var log = Path.Combine(item.Path, "console.log");
        if (File.Exists(log))
        {
            using var stream = new FileStream(log, FileMode.Open, FileAccess.Read, FileShare.ReadWrite);
            stream.Seek(Math.Max(0, stream.Length - 100_000), SeekOrigin.Begin);
            using var reader = new StreamReader(stream);
            text += "\n\n最近日志：\n" + await reader.ReadToEndAsync();
        }
        HistoryText.Text = text;
    });

    public async Task LoadSmoke(string workspace, string python)
    {
        var step = new JsonArray("action", JsonSerializer.Serialize(new { name = "领取礼物", target = "收取确认" }));
        var readable = StatusDisplay.FormatStep(step);
        if (!readable.Contains("领取礼物") || readable.Contains("\\u"))
            throw new InvalidOperationException("旧状态日志的 Unicode 转义解码失败");
        bool missingPython = false;
        try { await PythonEnvironment.RequireReady(new Settings { Python = Path.Combine(workspace, "absent.exe") }); }
        catch (IOException error) { missingPython = error.Message.Contains("下载 Python"); }
        if (!missingPython) throw new InvalidOperationException("未安装 Python 时缺少引导提示");
        if (await PythonEnvironment.Detect(python, workspace) != Path.GetFullPath(python))
            throw new InvalidOperationException("已安装 Python 检测失败");
        WorkspaceBox.Text = Path.GetFullPath(workspace);
        PythonBox.Text = Path.GetFullPath(python);
        string[] arguments = ["", "空格 path", "C:\\trailing path\\", "embedded\"quote", "& $(literal)"];
        var echoed = JsonNode.Parse(await Backend.Command(python,
            new[] { "-c", "import sys,json;print(json.dumps([sys.argv[1:],sys.stdin.read()],ensure_ascii=False))" }.Concat(arguments),
            workspace, "中文输入\n第二行"))!.AsArray();
        if (!echoed[0]!.AsArray().Select(value => value!.GetValue<string>()).SequenceEqual(arguments)
            || echoed[1]!.GetValue<string>() != "中文输入\n第二行")
            throw new InvalidOperationException("Windows 参数转义或 UTF-8 管道校验失败");
        bool timedOut = false;
        try { await Backend.Command(python, ["-c", "import time;time.sleep(10)"], workspace, timeoutSeconds: 1); }
        catch (TimeoutException) { timedOut = true; }
        if (!timedOut) throw new InvalidOperationException("辅助进程超时终止校验失败");
        await CreateNewConfig();
        if (_plan.Count != 0 || TaskPicker.Items.Count < 1) throw new InvalidOperationException("任务绑定失败");
        TaskPicker.SelectedItem = TaskPicker.Items.Cast<TaskChoice>().Single(t => t.Name == "campaign_clean");
        if (_parameters.Count != 2 || ParameterValues().Count != 2) throw new InvalidOperationException("动态参数表单失败");
        if (CatalogList.Items.Cast<TaskChoice>().Any(t => string.IsNullOrWhiteSpace(t.Description)))
            throw new InvalidOperationException("任务能力说明缺失");
        if (_optionEditors.Count == 0 || ReadOptions()["Extra"] is null) throw new InvalidOperationException("公共配置表单失败");
        if (TaskPicker.Items.Cast<TaskChoice>().Any(t => t.Category != "daily") ||
            CatalogList.Items.Cast<TaskChoice>().Any(t => t.Category != "special") ||
            !CatalogList.Items.Cast<TaskChoice>().Any(t => t.Name == "dungeon_first_clear"))
            throw new InvalidOperationException("日常与专项分类失败");
        CatalogList.SelectedItem = CatalogList.Items.Cast<TaskChoice>().Single(t => t.Name == "dungeon_first_clear");
        var dailyBefore = ReadOptions().ToJsonString();
        var specialToggle = _specialOptionEditors.Select(item => item.Editor).OfType<CheckBox>().First();
        specialToggle.IsChecked = specialToggle.IsChecked != true;
        if (ReadOptions().ToJsonString() != dailyBefore || _plan.Count != 0)
            throw new InvalidOperationException("专项选项污染日常配置");
        // Generate a new configuration using the actual GUI save path, without
        // touching existing user files or GUI preferences. Only sample data.
        await CreateNewConfig();
        if (_plan.Count != 0) throw new InvalidOperationException("新建配置并非空白");
        _plan.Add(new TaskRow { Name = "get_gift", Args = "[true]" });
        var generated = Path.Combine(workspace, "cache", "desktop", "smoke", Guid.NewGuid() + ".yml");
        await SaveToNewPath(generated, remember: false);
        await LoadConfig(saveSettings: false);
        if (_plan.Count != 1 || _plan[0].Name != "get_gift") throw new InvalidOperationException("配置生成/重载失败");
        var fixture = Path.Combine(workspace, "cache", "desktop", "smoke", Guid.NewGuid().ToString());
        Directory.CreateDirectory(fixture);
        if (PreferredConfig(fixture, "absent.yml") is not null) throw new InvalidOperationException("缺失配置检查失败");
        var fallback = Path.Combine(fixture, "daily_config.yml");
        File.Copy(generated, fallback);
        if (PreferredConfig(fixture, "absent.yml") != Path.GetFullPath(fallback) || PreferredConfig(fixture, generated) != Path.GetFullPath(generated))
            throw new InvalidOperationException("默认配置选择失败");
        TaskPicker.SelectedItem = TaskPicker.Items.Cast<TaskChoice>().Single(t => t.Name == "get_gift");
        _timer.Stop();
        StatusText.Text = "运行中 · 离线界面样例\n当前步骤：" + readable;
    }

    public void SelectSmokeTab(int index)
    {
        Tabs.SelectedIndex = index;
        if (index == 1) CatalogList.SelectedItem = CatalogList.Items.Cast<TaskChoice>().Single(t => t.Name == "dungeon_first_clear");
    }
}

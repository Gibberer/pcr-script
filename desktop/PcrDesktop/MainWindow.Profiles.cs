using System.IO;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace PcrDesktop;

public partial class MainWindow
{
    private void SetCatalog(JsonArray data)
    {
        var choices = data.Select(item => new TaskChoice(item!["name"]!.GetValue<string>(),
            item["label"]!.GetValue<string>(), item["parameters"]!.AsArray(),
            (item["description"]?.GetValue<string>() ?? "暂无任务说明") + "\n\n起始页面：" + (item["entry"]?.ToString() ?? "见任务说明"))).ToList();
        TaskPicker.ItemsSource = choices;
        CatalogList.ItemsSource = choices;
        TaskPicker.SelectedIndex = 0;
        CatalogList.SelectedIndex = 0;
    }

    private void RefreshConfigChoices()
    {
        var files = new List<string>();
        var workspace = WorkspaceBox.Text.Trim();
        if (Directory.Exists(workspace))
        {
            var defaultFile = Path.Combine(workspace, "daily_config.yml");
            if (File.Exists(defaultFile)) files.Add(Path.GetFullPath(defaultFile));
            var profiles = Path.Combine(workspace, "cache", "desktop", "profiles");
            if (Directory.Exists(profiles)) files.AddRange(Directory.GetFiles(profiles, "*.y*ml"));
        }
        files.AddRange(_settings.RecentConfigs.Where(File.Exists));
        ConfigPicker.ItemsSource = files.Distinct(StringComparer.OrdinalIgnoreCase).ToList();
        var config = ConfigBox.Text.Trim();
        if (config.Length > 0 && Directory.Exists(workspace))
            ConfigPicker.SelectedItem = Path.GetFullPath(Path.Combine(Path.GetFullPath(workspace), config));
    }

    private void RememberConfig(Settings settings)
    {
        var path = Path.GetFullPath(Path.Combine(settings.Workspace, settings.Config));
        settings.RecentConfigs = settings.RecentConfigs.Prepend(path).Distinct(StringComparer.OrdinalIgnoreCase).Take(20).ToList();
        _settings = settings;
        settings.Save();
        RefreshConfigChoices();
    }

    private async Task CreateNewConfig()
    {
        var settings = ReadSettings();
        await Idle(settings);
        await LoadRunOptions();
    }

    private async Task LoadRunOptions()
    {
        var settings = ReadSettings();
        var data = await Backend.Request(settings, "new");
        SetCatalog(data["catalog"]!.AsArray());
        _plan.Clear();
        OptionsBox.Text = data["options"]!.ToJsonString(_pretty);
        BuildOptions(data["options"]!.AsObject());
        _revision = "";
        _newConfig = true;
        ConfigBox.Text = "";
        _loadedSettings = ReadSettings();
        CurrentConfigText.Text = "未保存的配置草稿 · 单任务可直接执行，无需保存；保存后可作为整组方案使用。";
        ConfigPicker.SelectedIndex = -1;
        Message("运行选项已就绪；填写雷电路径后可直接运行单任务，整组方案可另行保存");
    }

    private async void Setup_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (_active || _process is { HasExited: false }) throw new InvalidOperationException("请先停止运行再修改工程或模拟器");
        var settings = Settings.Load();
        if (new SetupWindow(settings) { Owner = this, WindowStartupLocation = WindowStartupLocation.CenterOwner }.ShowDialog() != true) return;
        _settings = settings;
        WorkspaceBox.Text = settings.Workspace; PythonBox.Text = settings.Python;
        RepositoryBox.Text = settings.Repository; BranchBox.Text = settings.Branch;
        DownloadScopeBox.SelectedIndex = settings.DownloadCoreOnly ? 0 : 1;
        BootstrapBox.Text = settings.BootstrapPython;
        EmulatorLabel.Text = "雷电目录：" + settings.EmulatorDirectory;
        RefreshConfigChoices();
        await LoadRunOptions();
    });

    private async Task SaveAs()
    {
        RequireLoaded();
        await Idle(_loadedSettings!);
        var folder = Path.Combine(_loadedSettings!.Workspace, "cache", "desktop", "profiles");
        Directory.CreateDirectory(folder);
        var dialog = new SaveFileDialog
        {
            Title = "保存独立任务配置", InitialDirectory = folder,
            FileName = _newConfig ? "新配置.yml" : Path.GetFileNameWithoutExtension(_loadedSettings.Config) + "-副本.yml",
            Filter = "YAML 配置|*.yml;*.yaml", DefaultExt = ".yml", AddExtension = true
        };
        if (dialog.ShowDialog(this) != true) return;
        await SaveToNewPath(dialog.FileName);
    }

    private async Task SaveToNewPath(string destination, bool remember = true)
    {
        if (File.Exists(destination)) throw new IOException("目标配置已存在，请另取文件名；编辑现有配置请使用保存");
        var request = ConfigRequest();
        request["revision"] = "";
        var source = _loadedSettings!.Config;
        var sourcePath = string.IsNullOrEmpty(source) ? "" : Path.GetFullPath(Path.Combine(_loadedSettings.Workspace, source));
        if (!_newConfig && File.Exists(sourcePath))
        {
            request["source"] = sourcePath;
            request["source_revision"] = _revision;
        }
        else request["new"] = true;
        var target = ReadSettings();
        target.Config = Path.GetFullPath(destination);
        var result = await Backend.Request(target, "save", request);
        _revision = result["revision"]!.GetValue<string>();
        _loadedSettings = target;
        _newConfig = false;
        ConfigBox.Text = target.Config;
        CurrentConfigText.Text = "当前配置：" + target.Config;
        if (remember) RememberConfig(target);
        Message("配置已生成：" + target.Config);
    }

    private async void NewConfig_Click(object sender, RoutedEventArgs e) => await Guard(CreateNewConfig);
    private async void SaveAs_Click(object sender, RoutedEventArgs e) => await Guard(SaveAs);
    private async void OpenConfig_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var dialog = new OpenFileDialog { Title = "打开任务配置", Filter = "YAML 配置|*.yml;*.yaml" };
        if (dialog.ShowDialog(this) == true)
        {
            var old = ConfigBox.Text;
            ConfigBox.Text = dialog.FileName;
            try { await LoadConfig(); }
            catch { ConfigBox.Text = old; throw; }
        }
    });
    private async void SelectConfig_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (ConfigPicker.SelectedItem is not string selected) throw new InvalidOperationException("请选择配置文件，或点击打开配置");
        var old = ConfigBox.Text;
        ConfigBox.Text = selected;
        try { await LoadConfig(); }
        catch { ConfigBox.Text = old; throw; }
    });
    private async void Catalog_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var data = await Backend.Request(ReadSettings(), "catalog");
        SetCatalog(data["catalog"]!.AsArray());
        Message($"当前工程支持 {CatalogList.Items.Count} 个任务");
    });
    private void Catalog_SelectionChanged(object sender, SelectionChangedEventArgs e)
    {
        if (CatalogList.SelectedItem is not TaskChoice task) return;
        CatalogTitle.Text = task.Label;
        CatalogDescription.Text = task.Description;
        CatalogParameters.Text = task.Parameters.Count == 0 ? "此任务没有位置参数。"
            : "可配置参数：\n" + string.Join("\n", task.Parameters.Select(p => $"• {p!["label"] ?? p["name"]}（{p["type"]}）"));
    }
    private async void UseCatalog_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (CatalogList.SelectedItem is not TaskChoice selected) return;
        if (_loadedSettings is null) await CreateNewConfig();
        TaskPicker.SelectedItem = TaskPicker.Items.Cast<TaskChoice>().Single(t => t.Name == selected.Name);
        Tabs.SelectedIndex = 0;
        Message("可编辑右侧参数后执行选中任务，或加入当前配置");
    });
}

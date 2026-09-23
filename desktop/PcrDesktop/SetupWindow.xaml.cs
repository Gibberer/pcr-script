using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace PcrDesktop;

public partial class SetupWindow : Window
{
    private readonly Settings _settings;
    private bool _busy;

    public SetupWindow(Settings settings)
    {
        _settings = settings;
        InitializeComponent();
        Repository.Text = settings.Repository;
        Branch.Text = settings.Branch;
        DownloadScope.SelectedIndex = settings.DownloadCoreOnly ? 0 : 1;
        ProjectPath.Text = settings.Workspace;
        EmulatorPath.Text = settings.EmulatorDirectory;
        PythonPath.Text = string.IsNullOrWhiteSpace(settings.Python) && Directory.Exists(settings.Workspace)
            ? Path.Combine(settings.Workspace, ".venv", "Scripts", "python.exe") : settings.Python;
        Bootstrap.Text = settings.BootstrapPython;
        InspectProject();
        if (!File.Exists(PythonPath.Text)) ProgressText.Text = "尚未准备 Python 环境。已有 Python 请检测后创建环境；没有 Python 请先点击官网下载。";
    }

    public static bool IsProject(string path) => Directory.Exists(Path.Combine(path, "pcrscript"))
        && Directory.Exists(Path.Combine(path, "images")) && File.Exists(Path.Combine(path, "requirements.txt"));

    public static bool IsReady(Settings settings) => settings.SetupCompleted && IsProject(settings.Workspace)
        && File.Exists(Path.Combine(settings.Workspace, "pcrscript", "desktop.py"))
        && File.Exists(Path.Combine(settings.Workspace, "desktop", "runtime_defaults.yml"))
        && File.Exists(Path.Combine(settings.EmulatorDirectory, "ldconsole.exe")) && File.Exists(settings.Python);

    private void InspectProject()
    {
        if (ProjectStatus is null || DownloadPanel is null) return;
        var path = ProjectPath.Text.Trim();
        if (path.Length == 0) { ProjectStatus.Text = "请选择已有工程目录，或填写新项目的下载目录。"; DownloadPanel.Visibility = Visibility.Collapsed; return; }
        if (IsProject(path))
        {
            ProjectStatus.Text = File.Exists(Path.Combine(path, "pcrscript", "desktop.py"))
                ? "已识别 PCR 工程，将直接使用现有源码。"
                : "已识别旧版 PCR 工程，但缺少 GUI 接口；请先更新源码，或下载到新的空目录。";
            DownloadPanel.Visibility = Visibility.Collapsed;
        }
        else
        {
            var occupied = Directory.Exists(path) && Directory.EnumerateFileSystemEntries(path).Any();
            ProjectStatus.Text = occupied ? "此目录不是 PCR 工程且已有文件，请选择项目目录或其他空目录。" : "未找到项目，可从 GitHub 下载。";
            DownloadPanel.Visibility = occupied ? Visibility.Collapsed : Visibility.Visible;
        }
    }

    private void Project_Changed(object sender, TextChangedEventArgs e)
    {
        try { InspectProject(); }
        catch (Exception error) { if (ProjectStatus is not null) ProjectStatus.Text = error.Message; }
    }

    private void ProjectBrowse_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "选择工程目录或用于下载项目的空目录" };
        if (dialog.ShowDialog(this) == true)
        {
            ProjectPath.Text = dialog.FolderName;
            PythonPath.Text = Path.Combine(dialog.FolderName, ".venv", "Scripts", "python.exe");
        }
    }

    private void EmulatorBrowse_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFolderDialog { Title = "选择包含 ldconsole.exe 的雷电安装目录" };
        if (dialog.ShowDialog(this) == true) EmulatorPath.Text = dialog.FolderName;
    }

    private void PythonBrowse_Click(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog { Title = "选择运行工程的 Python", Filter = "Python 解释器|python.exe|程序|*.exe" };
        if (dialog.ShowDialog(this) == true) PythonPath.Text = dialog.FileName;
    }

    private async Task Guard(Func<Task> action)
    {
        if (_busy) return;
        _busy = true;
        SetupFields.IsEnabled = false;
        FinishButton.IsEnabled = DownloadButton.IsEnabled = false;
        try { await action(); }
        catch (Exception error) { ProgressText.Text = error.Message; }
        finally { _busy = false; SetupFields.IsEnabled = true; FinishButton.IsEnabled = DownloadButton.IsEnabled = true; }
    }

    private void Progress(string text) => Dispatcher.Invoke(() => ProgressText.Text = text);

    private string Project()
    {
        if (string.IsNullOrWhiteSpace(ProjectPath.Text)) throw new IOException("请选择工程目录");
        var root = Path.GetFullPath(ProjectPath.Text.Trim());
        if (!IsProject(root) || !File.Exists(Path.Combine(root, "pcrscript", "desktop.py")) ||
            !File.Exists(Path.Combine(root, "desktop", "runtime_defaults.yml")))
            throw new IOException("工程缺少新版 GUI 运行文件，请先更新源码或重新下载");
        return root;
    }

    private async void Download_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (string.IsNullOrWhiteSpace(ProjectPath.Text)) throw new IOException("请先选择下载目录");
        var target = Path.GetFullPath(ProjectPath.Text.Trim());
        if (File.Exists(target) || (Directory.Exists(target) && Directory.EnumerateFileSystemEntries(target).Any()))
            throw new IOException("目标目录已有文件，下载已取消，不会覆盖");
        var parent = Path.GetDirectoryName(target) ?? throw new IOException("不能使用磁盘根目录");
        Directory.CreateDirectory(parent);
        Progress("正在从 GitHub 下载项目…");
        await RuntimeSource.Download(Repository.Text.Trim(), Branch.Text.Trim(), target, Progress, coreOnly: DownloadScope.SelectedIndex == 0);
        InspectProject();
        PythonPath.Text = Path.Combine(target, ".venv", "Scripts", "python.exe");
        Progress("下载完成，请创建 Python 环境 / 安装依赖");
    });

    private void PythonDownload_Click(object sender, RoutedEventArgs e) => PythonEnvironment.OpenDownload();
    private async void DetectPython_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var cwd = Directory.Exists(ProjectPath.Text) ? ProjectPath.Text : AppDomain.CurrentDomain.BaseDirectory;
        Bootstrap.Text = await PythonEnvironment.Detect(Bootstrap.Text.Trim(), cwd);
        Progress("已检测到 " + Bootstrap.Text + "。请选择工程后创建环境 / 安装依赖。");
    });

    private async void Install_Click(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var project = Project();
        PythonPath.Text = await PythonEnvironment.Install(project, Bootstrap.Text.Trim(), Progress);
        Progress("环境准备完成，可点击完成进入控制台");
    });

    private async void Finish_Click(object sender, RoutedEventArgs e)
    {
        bool finished = false;
        await Guard(async () =>
        {
            var project = Project();
            var emulator = Path.GetFullPath(EmulatorPath.Text.Trim());
            if (!File.Exists(Path.Combine(emulator, "ldconsole.exe"))) throw new IOException("雷电目录中没有 ldconsole.exe，请重新选择");
            var python = Path.GetFullPath(PythonPath.Text.Trim());
            if (!File.Exists(python)) throw new IOException(PythonEnvironment.InstallHint);
            var candidate = new Settings { Workspace = project, Python = python };
            await Backend.Request(candidate, "catalog");
            _settings.Workspace = project; _settings.Python = python;
            _settings.EmulatorDirectory = emulator; _settings.SetupCompleted = true;
            _settings.BootstrapPython = Bootstrap.Text.Trim();
            _settings.Repository = Repository.Text.Trim(); _settings.Branch = Branch.Text.Trim();
            _settings.DownloadCoreOnly = DownloadScope.SelectedIndex == 0;
            _settings.Save();
            finished = true;
        });
        if (finished) DialogResult = true;
    }

    private void Setup_Closing(object? sender, CancelEventArgs e)
    {
        if (_busy) { e.Cancel = true; ProgressText.Text = "正在下载或准备环境，请等待完成后关闭。"; }
    }
}

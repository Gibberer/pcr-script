using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json.Nodes;

namespace PcrDesktop;

internal static class PythonEnvironment
{
    internal const string InstallHint = "Python 环境尚未就绪。请在环境设置点击“一键准备运行环境”，自动下载 Python、创建 .venv 并安装依赖；无需提前安装 Python。也可通过“下载 Python（官网）”手动安装 3.12 x64 后选择解释器。";

    internal static void OpenDownload() => Process.Start(new ProcessStartInfo("https://www.python.org/downloads/windows/") { UseShellExecute = true });

    internal static async Task<string> Detect(string preferred, string workspace)
    {
        var candidates = new List<string>();
        if (File.Exists(preferred)) candidates.Add(Path.GetFullPath(preferred));
        candidates.Add(PortableTools.Executable(PortableTools.Python));
        foreach (var directory in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator))
        {
            if (directory.IndexOf("WindowsApps", StringComparison.OrdinalIgnoreCase) >= 0) continue;
            try { candidates.Add(Path.Combine(directory.Trim('"'), "python.exe")); }
            catch (ArgumentException) { }
        }
        var installRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Python");
        if (Directory.Exists(installRoot))
            candidates.AddRange(Directory.GetDirectories(installRoot).OrderByDescending(p => p).Select(p => Path.Combine(p, "python.exe")));
        foreach (var executable in candidates.Where(File.Exists).Distinct(StringComparer.OrdinalIgnoreCase))
        {
            try
            {
                var output = await Backend.Command(executable, ["-I", "-c",
                    "import sys,struct;assert sys.version_info>=(3,12) and struct.calcsize('P')==8;print(sys.executable)"], workspace, timeoutSeconds: 10);
                return output.Trim();
            }
            catch (Exception error) when (error is IOException or Win32Exception or TimeoutException) { }
        }
        throw new IOException(InstallHint);
    }

    internal static async Task RequireReady(Settings settings)
    {
        if (!File.Exists(settings.Python)) throw new IOException(InstallHint);
        var result = JsonNode.Parse(await Backend.Command(settings.Python,
            ["-X", "utf8", "pcrscript/desktop.py", "environment"], settings.Workspace))!.AsObject();
        if (result["compatible"]?.GetValue<bool>() != true) throw new IOException(InstallHint);
        if (result["ready"]?.GetValue<bool>() != true)
            throw new IOException("Python 已找到，但缺少依赖：" +
                string.Join("、", result["missing"]!.AsArray().Select(item => item!.GetValue<string>())) +
                "。请在环境设置点击“一键准备运行环境”。下载需要联网。");
    }

    internal static async Task<string> Install(string workspace, string bootstrap, Action<string> log)
    {
        if (!SetupWindow.IsReady(new Settings { Workspace = workspace })) throw new IOException("请先下载或选择有效工程。");
        var logs = Path.Combine(workspace, "cache", "desktop", "setup");
        Directory.CreateDirectory(logs);
        var logPath = Path.Combine(logs, DateTime.Now.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N") + ".log");
        using var writer = new StreamWriter(logPath) { AutoFlush = true };
        void Report(string text) { lock (writer) writer.WriteLine(text); log(text); }
        Report("安装日志：" + logPath);
        try { return await InstallCore(workspace, bootstrap, Report); }
        catch (Exception error) { Report(error.Message); throw new IOException(error.Message + "\n完整日志：" + logPath, error); }
    }

    private static async Task<string> InstallCore(string workspace, string bootstrap, Action<string> log)
    {
        var python = Path.Combine(workspace, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python))
        {
            string installed;
            try { installed = await Detect(bootstrap, workspace); }
            catch (IOException)
            {
                installed = await PortableTools.Ensure(PortableTools.Python, log);
            }
            // The stdlib-only idle endpoint works before dependencies are installed.
            await Backend.Request(new Settings { Workspace = workspace, Python = installed }, "idle");
            log("正在使用 " + installed + " 创建项目专用环境…");
            await Backend.Command(installed, ["-m", "venv", ".venv"], workspace, log: log, timeoutSeconds: 300);
        }
        await Backend.Request(new Settings { Workspace = workspace, Python = python }, "idle");
        try
        {
            log("正在安装依赖（需要联网，首次安装可能需要数分钟）…");
            await Backend.Command(python, ["-m", "ensurepip", "--upgrade"], workspace, log: log);
            await Backend.Command(python, ["-m", "pip", "install", "--retries", "2", "--timeout", "30", "-r", "requirements.txt"],
                workspace, log: log, timeoutSeconds: 1800);
            await Backend.Command(python, ["-m", "pip", "check"], workspace, log: log);
            // Distribution metadata alone cannot detect missing native DLLs or import failures.
            await Backend.Command(python, ["-X", "utf8", "-c", "import cv2,numpy,win32api,yaml,requests,rapidocr,onnxruntime,playwright.sync_api;print('依赖导入检查通过')"], workspace, log: log);
        }
        catch (Exception error) when (error is IOException or TimeoutException)
        {
            throw new IOException("依赖安装未完成。请检查网络/代理和磁盘空间后重试；建议使用 Python 3.12 x64。已有环境会保留，可再次点击“一键准备运行环境”。\n" + error.Message, error);
        }
        await RequireReady(new Settings { Workspace = workspace, Python = python });
        return python;
    }
}

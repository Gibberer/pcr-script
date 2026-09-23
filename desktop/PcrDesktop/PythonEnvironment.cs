using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Text.Json.Nodes;

namespace PcrDesktop;

internal static class PythonEnvironment
{
    internal const string InstallHint = "未找到可用的 64 位 Python 3.12+。请点击“下载 Python”进入官网，安装时勾选 Add python.exe to PATH；建议 Python 3.12 x64。安装后点击“检测 Python”，再创建环境 / 安装依赖。";

    internal static void OpenDownload() => Process.Start(new ProcessStartInfo("https://www.python.org/downloads/windows/") { UseShellExecute = true });

    internal static async Task<string> Detect(string preferred, string workspace)
    {
        var candidates = new List<string>();
        if (File.Exists(preferred)) candidates.Add(Path.GetFullPath(preferred));
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
            throw new IOException("Python 已找到，但依赖未安装或版本不匹配：" +
                string.Join("、", result["missing"]!.AsArray().Select(item => item!.GetValue<string>())) +
                "。请点击“创建环境 / 安装依赖”，完成后重新检测。下载需要联网。");
    }

    internal static async Task<string> Install(string workspace, string bootstrap, Action<string> log)
    {
        var python = Path.Combine(workspace, ".venv", "Scripts", "python.exe");
        if (!File.Exists(python))
        {
            var installed = await Detect(bootstrap, workspace);
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
        }
        catch (Exception error) when (error is IOException or TimeoutException)
        {
            throw new IOException("依赖安装未完成。请检查网络/代理和磁盘空间后重试；建议使用 Python 3.12 x64。已有环境会保留，可再次点击安装。\n" + error.Message, error);
        }
        await RequireReady(new Settings { Workspace = workspace, Python = python });
        return python;
    }
}

using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.Json.Nodes;

namespace PcrDesktop;

public static class Backend
{
    static Backend()
    {
        // Let Windows inherit the environment directly. Framework's copied
        // dictionary can reject PATH/Path duplicates inherited from launchers.
        Environment.SetEnvironmentVariable("PYTHONUTF8", "1");
        Environment.SetEnvironmentVariable("PYTHONUNBUFFERED", "1");
        Environment.SetEnvironmentVariable("GIT_TERMINAL_PROMPT", "0");
    }

    public static Process Start(string executable, IEnumerable<string> arguments, string directory)
    {
        var info = new ProcessStartInfo(executable)
        {
            WorkingDirectory = directory, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true, RedirectStandardInput = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        info.Arguments = string.Join(" ", arguments.Select(WindowsCompatibility.QuoteArgument));
        return Process.Start(info) ?? throw new IOException("无法启动进程");
    }

    public static async Task<string> Command(string exe, IEnumerable<string> args, string cwd,
        string? input = null, Action<string>? log = null, int timeoutSeconds = 120)
    {
        using var process = Start(exe, args, cwd);
        var output = new StringBuilder();
        var errors = new StringBuilder();
        async Task Read(StreamReader stream, StringBuilder target)
        {
            while (await stream.ReadLineAsync() is { } line)
            {
                target.AppendLine(line);
                log?.Invoke(line);
            }
        }
        var stdout = Read(process.StandardOutput, output);
        var stderr = Read(process.StandardError, errors);
        await WriteInput(process, input);
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(timeoutSeconds));
        try { await process.WaitForExitAsync(deadline.Token); }
        catch (OperationCanceledException)
        {
            if (!process.HasExited) WindowsCompatibility.KillTree(process);
            await process.WaitForExitAsync();
            await Task.WhenAll(stdout, stderr);
            throw new TimeoutException("命令超时，已结束该辅助进程");
        }
        await Task.WhenAll(stdout, stderr);
        if (process.ExitCode != 0) throw new IOException($"命令失败（{process.ExitCode}）：{errors}\n{output}");
        return output.ToString();
    }

    public static async Task WriteInput(Process process, string? input)
    {
        // Framework's Process.StandardInput uses the console code page by default.
        using var writer = new StreamWriter(process.StandardInput.BaseStream, new UTF8Encoding(false));
        if (input is not null) await writer.WriteAsync(input);
    }

    public static async Task<JsonObject> Request(Settings settings, string command, JsonNode? body = null,
        params string[] extra)
    {
        if (command is "catalog" or "new" or "load" or "save") await PythonEnvironment.RequireReady(settings);
        var args = new List<string> { "-X", "utf8", "pcrscript/desktop.py", command, "--config", settings.Config };
        args.AddRange(extra);
        var text = await Command(settings.Python, args, settings.Workspace, body?.ToJsonString());
        var result = JsonNode.Parse(text)?.AsObject() ?? throw new IOException("Python 未返回有效协议数据");
        if (result["protocol"]?.GetValue<int>() != 1) throw new IOException("Python 协议版本不兼容，请更新 GUI / 脚本");
        return result;
    }

    public static JsonObject ReadObject(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        return JsonNode.Parse(stream)?.AsObject() ?? new();
    }
}

using System.ComponentModel;
using System.IO;
using System.IO.Compression;
using System.Net.Http;
using System.Security.Cryptography;

namespace PcrDesktop;

/// <summary>Private, versioned tools. No registry, system PATH or global pip changes.</summary>
internal static class PortableTools
{
    internal sealed record Package(string Name, string Url, string Sha256, string Executable);

    // Python's official NuGet distribution includes venv and ensurepip (unlike embedded Python).
    internal static readonly Package Python = new("python-3.12.10",
        "https://api.nuget.org/v3-flatcontainer/python/3.12.10/python.3.12.10.nupkg",
        "0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8", "tools/python.exe");
    internal static readonly Package Git = new("mingit-2.55.0.5",
        "https://github.com/git-for-windows/git/releases/download/v2.55.0.windows.5/MinGit-2.55.0.5-64-bit.zip",
        "56d7b226b7693196cfc71fef26568f536c4a021ab6c37ff2db4287bed908e96e", "cmd/git.exe");
    internal static readonly Package Adb = new("platform-tools-37.0.1",
        "https://dl.google.com/android/repository/platform-tools_r37.0.1-win.zip",
        "45f4d63113e895ebde0c90f194099a4676b6ac653bd28d54314a9e022bbc1a99", "platform-tools/adb.exe");

    internal static string Root => Path.Combine(Path.GetDirectoryName(Settings.FilePath)!, "tools");
    internal static string Executable(Package package) => Path.Combine(Root, package.Name, package.Executable);

    internal static async Task<string> EnsureGit(string cwd, Action<string>? log = null, string? root = null)
    {
        try { await Backend.Command("git", ["--version"], cwd, timeoutSeconds: 10); return "git"; }
        catch (Exception error) when (error is IOException or Win32Exception or TimeoutException) { }
        var git = await Ensure(Git, log, root);
        await Backend.Command(git, ["--version"], cwd, timeoutSeconds: 10);
        return git;
    }

    internal static async Task<string> Ensure(Package package, Action<string>? log = null, string? root = null)
    {
        root ??= Root;
        Directory.CreateDirectory(root);
        var target = Path.Combine(root, package.Name);
        var executable = Path.Combine(target, package.Executable);
        if (File.Exists(executable) && File.Exists(Path.Combine(target, ".complete"))) return executable;
        // Only this package's unique staging directory is ever removed. A failed extraction is never published.
        using var installLock = new FileStream(Path.Combine(root, package.Name + ".lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        if (Directory.Exists(target)) throw new IOException("工具目录不完整，请将此目录改名后重试：" + target);
        var stage = Path.Combine(root, ".install-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stage);
        try
        {
            var zip = Path.Combine(stage, "download.zip");
            log?.Invoke("正在下载 " + package.Name + "（首次需要联网）…");
            await Download(package.Url, zip, log);
            await Task.Run(() => VerifyHash(zip, package.Sha256));
            var files = Path.Combine(stage, "files");
            await Task.Run(() => Extract(zip, files));
            if (!File.Exists(Path.Combine(files, package.Executable))) throw new IOException("下载包缺少程序：" + package.Executable);
            File.WriteAllText(Path.Combine(files, ".complete"), package.Sha256);
            Directory.Move(files, target);
            log?.Invoke(package.Name + " 已准备完成。");
            return executable;
        }
        catch (Exception error) when (error is HttpRequestException or TaskCanceledException or IOException or InvalidDataException)
        {
            throw new IOException(package.Name + " 准备失败。请检查网络/代理和磁盘空间后重试；已完成的工具会保留。\n" + error.Message, error);
        }
        finally { if (Directory.Exists(stage)) Directory.Delete(stage, true); }
    }

    private static async Task Download(string url, string destination, Action<string>? log)
    {
        using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(10) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd("PcrDesktop/1.0");
        using var deadline = new CancellationTokenSource(TimeSpan.FromMinutes(10));
        using var response = await client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, deadline.Token);
        response.EnsureSuccessStatusCode();
        using var source = await response.Content.ReadAsStreamAsync();
        using var file = File.Create(destination);
        var buffer = new byte[81920];
        long total = 0;
        var last = DateTime.UtcNow;
        int count;
        while ((count = await source.ReadAsync(buffer, 0, buffer.Length, deadline.Token)) > 0)
        {
            await file.WriteAsync(buffer, 0, count, deadline.Token);
            total += count;
            if ((DateTime.UtcNow - last).TotalSeconds >= 2)
            {
                log?.Invoke($"已下载 {total / 1048576.0:F1} MB…");
                last = DateTime.UtcNow;
            }
        }
    }

    internal static void VerifyHash(string path, string expected)
    {
        using var sha = SHA256.Create();
        using var file = File.OpenRead(path);
        var actual = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "");
        if (!actual.Equals(expected, StringComparison.OrdinalIgnoreCase))
            throw new IOException("下载校验失败，未执行或解压文件；请重试或更新 GUI。");
    }

    internal static void Extract(string zip, string target)
    {
        var root = Path.GetFullPath(target).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        using var archive = ZipFile.OpenRead(zip);
        foreach (var entry in archive.Entries)
        {
            var name = entry.FullName.Replace('/', Path.DirectorySeparatorChar);
            if (name.Contains(':') || Path.IsPathRooted(name) || ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                throw new IOException("下载包包含不安全路径");
            var path = Path.GetFullPath(Path.Combine(root, name));
            if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase))
                throw new IOException("下载包包含不安全路径");
            if (string.IsNullOrEmpty(entry.Name)) { Directory.CreateDirectory(path); continue; }
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            entry.ExtractToFile(path); // Duplicate paths are rejected, not overwritten.
        }
    }
}
